"""drop weight, add scheduled_end, reset user_settings

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-09 14:03:04.993700

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop weight column (and its CHECK constraint) from tasks; add scheduled_end.
    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_tasks_weight_range", type_="check")
        batch_op.drop_column("weight")
        batch_op.add_column(
            sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True)
        )

    # Reset user_settings: existing rows have day_type_rules with old field names
    # (allowed_weight_max). On next GET /settings the row is regenerated with the
    # new schema (allowed_max_task_duration_min).
    op.execute("DELETE FROM user_settings")


def downgrade() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.drop_column("scheduled_end")
        batch_op.add_column(
            sa.Column(
                "weight",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.5"),
            )
        )
        batch_op.create_check_constraint(
            "ck_tasks_weight_range", "weight >= 0 AND weight <= 1"
        )
    # user_settings can't be restored to old schema cleanly; user must re-customize.
