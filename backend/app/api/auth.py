from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import User
from app.schemas.auth import CurrentUser
from app.services.google import oauth as oauth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google/local", response_model=CurrentUser)
async def login_local(db: AsyncSession = Depends(get_db)) -> CurrentUser:
    """Run the OAuth InstalledAppFlow locally. A browser window will open."""
    try:
        user = await oauth_service.start_local_flow(db)
    except oauth_service.GoogleAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "oauth_failed", "message": str(e)},
        ) from e

    info = await oauth_service.get_credential_info(db, user.id)
    scopes, expires_at = info if info is not None else ([], None)
    return CurrentUser(
        user_id=user.id,
        google_email=user.google_email,
        scopes=scopes,
        token_expires_at=expires_at,
    )


@router.get("/me", response_model=CurrentUser)
async def me(db: AsyncSession = Depends(get_db)) -> CurrentUser:
    from sqlalchemy import select

    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": "No user. Run /auth/google/local."},
        )
    info = await oauth_service.get_credential_info(db, user.id)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": "No OAuth credentials."},
        )
    scopes, expires_at = info
    return CurrentUser(
        user_id=user.id,
        google_email=user.google_email,
        scopes=scopes,
        token_expires_at=expires_at,
    )


@router.delete("/google", status_code=status.HTTP_204_NO_CONTENT)
async def logout(db: AsyncSession = Depends(get_db)) -> None:
    from sqlalchemy import select

    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if user is None:
        return
    await oauth_service.delete_credentials(db, user.id)
