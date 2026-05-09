from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OptimizerSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "optimizer_snapshots"

    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tasks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    slots_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
