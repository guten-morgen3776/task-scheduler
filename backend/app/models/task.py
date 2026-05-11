from datetime import datetime

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.types import UTCDateTime


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tasks"

    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    list_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("task_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    position: Mapped[str] = mapped_column(String(64), nullable=False)

    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    due: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    location: Mapped[str | None] = mapped_column(String(32), nullable=True)

    scheduled_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # List of {"start": iso, "end": iso} per fragment when the task is split
    # across multiple slots. None or empty when not yet placed.
    scheduled_fragments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    # When True, the task's current placement is locked: subsequent /optimize
    # runs leave its scheduled_* fields untouched and treat the time as busy
    # for everything else.
    scheduled_fixed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    __table_args__ = (
        CheckConstraint("priority >= 1 AND priority <= 5", name="ck_tasks_priority_range"),
        CheckConstraint("duration_min > 0", name="ck_tasks_duration_positive"),
        Index("ix_tasks_user_list_position", "user_id", "list_id", "position"),
        Index("ix_tasks_user_completed_deadline", "user_id", "completed", "deadline"),
    )
