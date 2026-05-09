"""add tasks.location and reset user_settings for location rules

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-09 14:38:29.132348

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("location", sa.String(length=32), nullable=True),
    )

    # user_settings: replace `location_buffers` with `calendar_location_rules`
    # + `location_commutes`. Existing rows are deleted; on next GET /settings
    # the row is regenerated with the new schema and defaults.
    op.execute("DELETE FROM user_settings")

    with op.batch_alter_table("user_settings", recreate="always") as batch_op:
        batch_op.drop_column("location_buffers")
        batch_op.add_column(
            sa.Column("calendar_location_rules", sa.JSON(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("location_commutes", sa.JSON(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings", recreate="always") as batch_op:
        batch_op.drop_column("calendar_location_rules")
        batch_op.drop_column("location_commutes")
        batch_op.add_column(sa.Column("location_buffers", sa.JSON(), nullable=False))
    op.drop_column("tasks", "location")
