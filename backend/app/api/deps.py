from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import User


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_or_create_default_user(db: AsyncSession) -> User:
    """Single-user MVP: return the only user, or create one on demand.

    Will be replaced with JWT-based auth when migrating to web flow (§8.2 Step B).
    """
    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if user is not None:
        return user
    user = User()
    db.add(user)
    await db.flush()
    return user


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "not_authenticated",
                "message": "No user. Run POST /auth/google/local first.",
            },
        )
    return user
