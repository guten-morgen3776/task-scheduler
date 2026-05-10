"""add tasks.scheduled_fragments JSON column

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("scheduled_fragments", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "scheduled_fragments")
