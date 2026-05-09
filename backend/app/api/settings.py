from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.settings import SettingsRead, SettingsUpdate, build_default_settings
from app.services.slots import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead, response_model_by_alias=True)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SettingsRead:
    return await settings_service.get_or_create_settings(db, user.id)


@router.put("", response_model=SettingsRead, response_model_by_alias=True)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SettingsRead:
    try:
        return await settings_service.update_settings(db, user.id, payload)
    except settings_service.SettingsValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": str(e)},
        ) from e


@router.post("/reset", response_model=SettingsRead, response_model_by_alias=True)
async def reset_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SettingsRead:
    """Overwrite with default settings."""
    defaults = build_default_settings()
    update = SettingsUpdate.model_validate(defaults.model_dump(by_alias=True))
    return await settings_service.update_settings(db, user.id, update)
