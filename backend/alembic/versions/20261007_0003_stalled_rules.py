"""stalled_rules configurable engine (no default thresholds)

Revision ID: 20261007_0003
Revises: 20251006_0002
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0003"
down_revision: Union[str, None] = "20251006_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stalled_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_bitrix_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_id", sa.Integer(), nullable=True),
        sa.Column("max_idle_minutes", sa.Integer(), nullable=True),
        sa.Column("future_activity_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_next_activity_minutes", sa.Integer(), nullable=True),
        sa.Column("deal_status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("use_business_calendar", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["stage_id"], ["crm_stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stalled_rules_pipeline_bitrix_id", "stalled_rules", ["pipeline_bitrix_id"])
    op.create_index("ix_stalled_rules_enabled", "stalled_rules", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_stalled_rules_enabled", table_name="stalled_rules")
    op.drop_index("ix_stalled_rules_pipeline_bitrix_id", table_name="stalled_rules")
    op.drop_table("stalled_rules")
