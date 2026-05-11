from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserSettings(Base, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    work_hours: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    calendar_location_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    location_commutes: Mapped[dict[str, dict[str, Any]]] = mapped_column(JSON, nullable=False)
    day_type_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    day_type_default: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    day_type_overrides: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    busy_calendar_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    ignore_calendar_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    slot_min_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_max_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    ignore_all_day_events: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # Locations the user is willing to voluntarily visit when their location-
    # tagged tasks don't fit existing event-based windows. e.g. ["university"].
    voluntary_visit_locations: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
