from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.calendar import CalendarEvent, CalendarInfo
from app.services.google import calendar as calendar_service
from app.services.google import oauth as oauth_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/calendars", response_model=list[CalendarInfo])
async def list_calendars(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CalendarInfo]:
    try:
        return await calendar_service.list_calendars(db, user.id)
    except oauth_service.NotAuthenticatedError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": str(e)},
        ) from e
    except oauth_service.ReauthRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "reauth_required", "message": str(e)},
        ) from e
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e


@router.get("/events", response_model=list[CalendarEvent])
async def list_events(
    start: datetime = Query(..., description="ISO8601 with timezone"),
    end: datetime = Query(..., description="ISO8601 with timezone"),
    calendar_id: str | None = Query(
        None, description="Single calendar id. Defaults to 'primary' if neither this nor calendar_ids is set."
    ),
    calendar_ids: str | None = Query(
        None,
        description=(
            "Comma-separated calendar ids. Overrides calendar_id when set. "
            "Events from each calendar are merged and sorted by start time."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CalendarEvent]:
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "validation_error",
                "message": "start and end must include a timezone offset",
            },
        )
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": "end must be after start"},
        )

    if calendar_ids is not None:
        ids = [c.strip() for c in calendar_ids.split(",") if c.strip()]
        if not ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "validation_error", "message": "calendar_ids is empty"},
            )
    elif calendar_id is not None:
        ids = [calendar_id]
    else:
        ids = ["primary"]

    try:
        return await calendar_service.list_events(
            db, user.id, start=start, end=end, calendar_ids=ids
        )
    except oauth_service.NotAuthenticatedError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": str(e)},
        ) from e
    except oauth_service.ReauthRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "reauth_required", "message": str(e)},
        ) from e
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e
