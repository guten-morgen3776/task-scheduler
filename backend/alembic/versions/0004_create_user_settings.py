"""create user_settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-09 12:26:34.343051

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("work_hours", sa.JSON(), nullable=False),
        sa.Column("location_buffers", sa.JSON(), nullable=False),
        sa.Column("day_type_rules", sa.JSON(), nullable=False),
        sa.Column("day_type_default", sa.JSON(), nullable=False),
        sa.Column("day_type_overrides", sa.JSON(), nullable=False),
        sa.Column("busy_calendar_ids", sa.JSON(), nullable=False),
        sa.Column("ignore_calendar_ids", sa.JSON(), nullable=False),
        sa.Column("slot_min_duration_min", sa.Integer(), nullable=False),
        sa.Column("slot_max_duration_min", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
