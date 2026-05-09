"""create optimizer_snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-09 13:42:27.248304

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "optimizer_snapshots",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tasks_json", sa.JSON(), nullable=False),
        sa.Column("slots_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_optimizer_snapshots_user_created",
        "optimizer_snapshots",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_optimizer_snapshots_user_created", table_name="optimizer_snapshots"
    )
    op.drop_table("optimizer_snapshots")
