"""deal_stage_history from crm.stagehistory.list + sync_type 'stage_history'

Revision ID: 20261102_0004
Revises: 20261102_0003
Create Date: 2026-11-02

Idempotent: 0001 builds tables (and the sync_type enum) from current models,
so a fresh database already has both.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261102_0004"
down_revision: Union[str, None] = "20261102_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE sync_type ADD VALUE IF NOT EXISTS 'stage_history'")
    if "deal_stage_history" in inspect(bind).get_table_names():
        return
    op.create_table(
        "deal_stage_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bitrix_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("deal_bitrix_id", sa.BigInteger(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=True),
        sa.Column("stage_bitrix_id", sa.String(length=64), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("semantics", sa.String(length=32), nullable=True),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deal_stage_history_deal_time", "deal_stage_history", ["deal_bitrix_id", "created_time"])
    op.create_index("ix_deal_stage_history_category", "deal_stage_history", ["category_id"])


def downgrade() -> None:
    # Postgres cannot drop a single enum value; the unused 'stage_history' value is harmless
    if "deal_stage_history" in inspect(op.get_bind()).get_table_names():
        op.drop_table("deal_stage_history")
