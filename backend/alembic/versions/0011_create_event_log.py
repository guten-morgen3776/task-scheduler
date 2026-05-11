"""create event_log

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-10 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_event_log_user_occurred",
        "event_log",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_event_log_user_type",
        "event_log",
        ["user_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_log_user_type", table_name="event_log")
    op.drop_index("ix_event_log_user_occurred", table_name="event_log")
    op.drop_table("event_log")
