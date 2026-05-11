"""add tasks.scheduled_fixed and user_settings.voluntary_visit_locations

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-10 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "scheduled_fixed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "voluntary_visit_locations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "voluntary_visit_locations")
    op.drop_column("tasks", "scheduled_fixed")
