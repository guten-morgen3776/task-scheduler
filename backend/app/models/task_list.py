from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskList(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "task_lists"

    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    position: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_task_lists_user_position", "user_id", "position"),
    )
