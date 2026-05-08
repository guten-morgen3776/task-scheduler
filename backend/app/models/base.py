import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.time import utc_now
from app.models.types import UTCDateTime


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return uuid.uuid4().hex


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=new_uuid,
    )
