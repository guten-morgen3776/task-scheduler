from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User
from app.services.google import calendar as calendar_service
from app.services.google import oauth as oauth_service
from app.services.slots import generator as slot_generator
from app.services.slots.domain import Slot

router = APIRouter(prefix="/calendar", tags=["slots"])


@router.get("/slots", response_model=list[Slot])
async def list_slots(
    start: datetime = Query(..., description="ISO8601 with timezone"),
    end: datetime = Query(..., description="ISO8601 with timezone"),
    min_duration_min: int | None = Query(default=None, gt=0),
    max_duration_min: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Slot]:
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

    try:
        return await slot_generator.generate_slots(
            db,
            user.id,
            start=start,
            end=end,
            min_duration_override=min_duration_min,
            max_duration_override=max_duration_min,
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
