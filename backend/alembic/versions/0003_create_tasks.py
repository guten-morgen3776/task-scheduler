"""create tasks

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-08 17:32:13.861402

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "list_id",
            sa.String(length=32),
            sa.ForeignKey("task_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "parent_id",
            sa.String(length=32),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("position", sa.String(length=64), nullable=False),
        sa.Column(
            "completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "duration_min",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_event_id", sa.String(length=255), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name="ck_tasks_weight_range"),
        sa.CheckConstraint("priority >= 1 AND priority <= 5", name="ck_tasks_priority_range"),
        sa.CheckConstraint("duration_min > 0", name="ck_tasks_duration_positive"),
    )
    op.create_index(
        "ix_tasks_user_list_position",
        "tasks",
        ["user_id", "list_id", "position"],
    )
    op.create_index(
        "ix_tasks_user_completed_deadline",
        "tasks",
        ["user_id", "completed", "deadline"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_user_completed_deadline", table_name="tasks")
    op.drop_index("ix_tasks_user_list_position", table_name="tasks")
    op.drop_table("tasks")
