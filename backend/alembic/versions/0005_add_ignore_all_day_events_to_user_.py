"""add ignore_all_day_events to user_settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-09 12:57:24.522046

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "ignore_all_day_events",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "ignore_all_day_events")
