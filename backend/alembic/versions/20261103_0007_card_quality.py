"""card quality: deal raw payload, timeline comments, per-stage rules, sync_type 'comments'

Revision ID: 20261103_0007
Revises: 20261103_0006
Create Date: 2026-11-03

Idempotent: 0001 builds tables (and the enum) from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261103_0007"
down_revision: Union[str, None] = "20261103_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE sync_type ADD VALUE IF NOT EXISTS 'comments'")
    insp = inspect(bind)
    if "raw" not in {c["name"] for c in insp.get_columns("crm_deals")}:
        op.add_column("crm_deals", sa.Column("raw", JSONB(), nullable=True))
    tables = insp.get_table_names()
    if "deal_comments" not in tables:
        op.create_table(
            "deal_comments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("bitrix_id", sa.BigInteger(), nullable=False, unique=True),
            sa.Column("deal_bitrix_id", sa.BigInteger(), nullable=False),
            sa.Column("author_id", sa.Integer(), nullable=True),
            sa.Column("created", sa.DateTime(timezone=True), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_deal_comments_deal_created", "deal_comments", ["deal_bitrix_id", "created"])
    if "card_quality_rules" not in tables:
        op.create_table(
            "card_quality_rules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("stage_bitrix_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("checks", JSONB(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    insp = inspect(op.get_bind())
    for table in ("card_quality_rules", "deal_comments"):
        if table in insp.get_table_names():
            op.drop_table(table)
    if "raw" in {c["name"] for c in insp.get_columns("crm_deals")}:
        op.drop_column("crm_deals", "raw")
