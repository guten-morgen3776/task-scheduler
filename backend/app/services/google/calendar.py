import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.calendar import CalendarEvent, CalendarInfo
from app.services.google import oauth as oauth_service

logger = logging.getLogger("app.google")


class CalendarApiError(Exception):
    pass


def _parse_event_time(value: dict[str, Any]) -> tuple[datetime, bool]:
    """Return (UTC datetime, all_day_flag)."""
    if "dateTime" in value:
        dt = date_parser.isoparse(value["dateTime"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC), False
    if "date" in value:
        d: date = date_parser.isoparse(value["date"]).date()
        return datetime(d.year, d.month, d.day, tzinfo=UTC), True
    raise CalendarApiError(f"Unrecognized event time payload: {value}")


def _normalize_event(raw: dict[str, Any], calendar_id: str) -> CalendarEvent:
    start, all_day_start = _parse_event_time(raw["start"])
    end, all_day_end = _parse_event_time(raw["end"])
    if all_day_end and start != end:
        end = end - timedelta(microseconds=1)
    status = raw.get("status", "confirmed")
    if status not in {"confirmed", "tentative", "cancelled"}:
        status = "confirmed"
    return CalendarEvent(
        id=raw["id"],
        calendar_id=calendar_id,
        summary=raw.get("summary") or "(no title)",
        description=raw.get("description"),
        start=start,
        end=end,
        all_day=all_day_start or all_day_end,
        location=raw.get("location"),
        status=status,
    )


async def list_calendars(db: AsyncSession, user_id: str) -> list[CalendarInfo]:
    creds = await oauth_service.load_credentials(db, user_id)

    def _call() -> list[dict[str, Any]]:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            resp = service.calendarList().list(pageToken=page_token).execute()
            items.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    try:
        raw = await asyncio.get_running_loop().run_in_executor(None, _call)
    except HttpError as e:
        logger.warning("calendarList API error: %s", e)
        raise CalendarApiError(str(e)) from e

    return [
        CalendarInfo(
            id=item["id"],
            summary=item.get("summary") or "(no title)",
            description=item.get("description"),
            primary=bool(item.get("primary", False)),
            access_role=item.get("accessRole", "reader"),
            background_color=item.get("backgroundColor"),
            selected=bool(item.get("selected", False)),
            time_zone=item.get("timeZone"),
        )
        for item in raw
    ]


async def list_events(
    db: AsyncSession,
    user_id: str,
    start: datetime,
    end: datetime,
    calendar_ids: list[str] | None = None,
) -> list[CalendarEvent]:
    """Fetch events from one or more calendars, merged and sorted by start time."""
    if calendar_ids is None or not calendar_ids:
        calendar_ids = ["primary"]

    creds = await oauth_service.load_credentials(db, user_id)

    def _call(calendar_id: str) -> list[dict[str, Any]]:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            resp = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=start.astimezone(UTC).isoformat(),
                    timeMax=end.astimezone(UTC).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                    maxResults=2500,
                )
                .execute()
            )
            events.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return events

    loop = asyncio.get_running_loop()
    merged: list[CalendarEvent] = []
    for cal_id in calendar_ids:
        try:
            raw_events = await loop.run_in_executor(None, _call, cal_id)
        except HttpError as e:
            logger.warning("Calendar API error for %s: %s", cal_id, e)
            raise CalendarApiError(f"{cal_id}: {e}") from e
        merged.extend(
            _normalize_event(ev, cal_id)
            for ev in raw_events
            if ev.get("status") != "cancelled"
        )

    merged.sort(key=lambda e: e.start)
    return merged
