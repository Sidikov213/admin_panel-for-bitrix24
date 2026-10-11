"""sales rules engine: rules, violations, audits, deal field metadata

Revision ID: 20261007_0004
Revises: 20261007_0003
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261007_0004"
down_revision: Union[str, None] = "20261007_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pipeline_bitrix_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_idle_minutes", sa.Integer(), nullable=True),
        sa.Column("future_activity_required", sa.Boolean(), nullable=True),
        sa.Column("max_next_activity_minutes", sa.Integer(), nullable=True),
        sa.Column("overdue_activity_allowed", sa.Boolean(), nullable=True),
        sa.Column("required_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("required_comment", sa.Boolean(), nullable=True),
        sa.Column("comment_max_age_minutes", sa.Integer(), nullable=True),
        sa.Column("max_stage_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("comments_capability", sa.String(length=32), nullable=False, server_default="unsupported"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["stage_id"], ["crm_stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_rules_pipeline_bitrix_id", "sales_rules", ["pipeline_bitrix_id"])
    op.create_index("ix_sales_rules_stage_id", "sales_rules", ["stage_id"])
    op.create_index("ix_sales_rules_enabled", "sales_rules", ["enabled"])
    op.create_index("ix_sales_rules_pipeline_stage", "sales_rules", ["pipeline_bitrix_id", "stage_id"])

    op.create_table(
        "sales_rule_violations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("violation_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("current_value", sa.String(length=512), nullable=True),
        sa.Column("threshold", sa.String(length=512), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("opportunity", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["deal_id"], ["crm_deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["sales_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_srv_deal_status", "sales_rule_violations", ["deal_id", "status"])
    op.create_index("ix_srv_type_status", "sales_rule_violations", ["violation_type", "status"])
    op.create_index("ix_srv_detected", "sales_rule_violations", ["detected_at"])
    op.create_index("ix_srv_resolved", "sales_rule_violations", ["resolved_at"])
    op.create_index("ix_sales_rule_violations_manager_id", "sales_rule_violations", ["manager_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_srv_open_deal_rule_type
        ON sales_rule_violations (deal_id, rule_id, violation_type)
        WHERE status = 'open'
        """
    )

    op.create_table(
        "sales_rule_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["sales_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_rule_audits_rule_id", "sales_rule_audits", ["rule_id"])

    op.create_table(
        "bitrix_deal_fields",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("is_required_in_bitrix", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_multiple", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_user_field", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_name"),
    )
    op.create_index("ix_bitrix_deal_fields_field_name", "bitrix_deal_fields", ["field_name"])


def downgrade() -> None:
    op.drop_index("ix_bitrix_deal_fields_field_name", table_name="bitrix_deal_fields")
    op.drop_table("bitrix_deal_fields")
    op.drop_index("ix_sales_rule_audits_rule_id", table_name="sales_rule_audits")
    op.drop_table("sales_rule_audits")
    op.execute("DROP INDEX IF EXISTS uq_srv_open_deal_rule_type")
    op.drop_index("ix_sales_rule_violations_manager_id", table_name="sales_rule_violations")
    op.drop_index("ix_srv_resolved", table_name="sales_rule_violations")
    op.drop_index("ix_srv_detected", table_name="sales_rule_violations")
    op.drop_index("ix_srv_type_status", table_name="sales_rule_violations")
    op.drop_index("ix_srv_deal_status", table_name="sales_rule_violations")
    op.drop_table("sales_rule_violations")
    op.drop_index("ix_sales_rules_pipeline_stage", table_name="sales_rules")
    op.drop_index("ix_sales_rules_enabled", table_name="sales_rules")
    op.drop_index("ix_sales_rules_stage_id", table_name="sales_rules")
    op.drop_index("ix_sales_rules_pipeline_bitrix_id", table_name="sales_rules")
    op.drop_table("sales_rules")
