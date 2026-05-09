from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSettings
from app.schemas.settings import SettingsRead, SettingsUpdate, build_default_settings


class SettingsValidationError(Exception):
    pass


def _to_db_kwargs(settings: SettingsRead) -> dict:
    return {
        "work_hours": settings.work_hours.model_dump(),
        "calendar_location_rules": [
            r.model_dump() for r in settings.calendar_location_rules
        ],
        "location_commutes": {
            loc: c.model_dump() for loc, c in settings.location_commutes.items()
        },
        "day_type_rules": [r.model_dump(by_alias=True) for r in settings.day_type_rules],
        "day_type_default": settings.day_type_default.model_dump(),
        "day_type_overrides": dict(settings.day_type_overrides),
        "busy_calendar_ids": list(settings.busy_calendar_ids),
        "ignore_calendar_ids": list(settings.ignore_calendar_ids),
        "slot_min_duration_min": settings.slot_min_duration_min,
        "slot_max_duration_min": settings.slot_max_duration_min,
        "ignore_all_day_events": settings.ignore_all_day_events,
    }


def _to_read(row: UserSettings) -> SettingsRead:
    return SettingsRead.model_validate(
        {
            "work_hours": row.work_hours,
            "calendar_location_rules": row.calendar_location_rules,
            "location_commutes": row.location_commutes,
            "day_type_rules": row.day_type_rules,
            "day_type_default": row.day_type_default,
            "day_type_overrides": row.day_type_overrides,
            "busy_calendar_ids": row.busy_calendar_ids,
            "ignore_calendar_ids": row.ignore_calendar_ids,
            "slot_min_duration_min": row.slot_min_duration_min,
            "slot_max_duration_min": row.slot_max_duration_min,
            "ignore_all_day_events": row.ignore_all_day_events,
        }
    )


async def get_or_create_settings(db: AsyncSession, user_id: str) -> SettingsRead:
    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is not None:
        return _to_read(row)

    defaults = build_default_settings()
    row = UserSettings(user_id=user_id, **_to_db_kwargs(defaults))
    db.add(row)
    await db.flush()
    return defaults


async def update_settings(
    db: AsyncSession, user_id: str, patch: SettingsUpdate
) -> SettingsRead:
    current = await get_or_create_settings(db, user_id)

    merged_dict = current.model_dump(by_alias=True)
    patch_dict = patch.model_dump(exclude_unset=True, by_alias=True)
    merged_dict.update(patch_dict)
    merged = SettingsRead.model_validate(merged_dict)

    if merged.slot_min_duration_min > merged.slot_max_duration_min:
        raise SettingsValidationError(
            f"slot_min_duration_min ({merged.slot_min_duration_min}) must not exceed "
            f"slot_max_duration_min ({merged.slot_max_duration_min})"
        )

    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one()
    for key, value in _to_db_kwargs(merged).items():
        setattr(row, key, value)
    await db.flush()
    return merged
