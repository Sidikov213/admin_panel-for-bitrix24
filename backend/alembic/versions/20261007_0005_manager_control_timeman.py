"""manager control: local timeman workday snapshots + aggregated days

Revision ID: 20261007_0005
Revises: 20261007_0004
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261007_0005"
down_revision: Union[str, None] = "20261007_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manager_workday_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("bitrix_user_id", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status_raw", sa.String(length=64), nullable=True),
        sa.Column("status_normalized", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("time_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_finish", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("duration_raw", sa.String(length=32), nullable=True),
        sa.Column("time_leaks_seconds", sa.Integer(), nullable=True),
        sa.Column("time_leaks_raw", sa.String(length=32), nullable=True),
        sa.Column("source_timezone", sa.String(length=64), nullable=True),
        sa.Column("tz_offset_seconds", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manager_id", "content_hash", name="uq_mws_manager_content_hash"),
    )
    op.create_index("ix_manager_workday_snapshots_manager_id", "manager_workday_snapshots", ["manager_id"])
    op.create_index("ix_manager_workday_snapshots_bitrix_user_id", "manager_workday_snapshots", ["bitrix_user_id"])
    op.create_index("ix_manager_workday_snapshots_work_date", "manager_workday_snapshots", ["work_date"])
    op.create_index("ix_mws_manager_observed", "manager_workday_snapshots", ["manager_id", "observed_at"])
    op.create_index("ix_mws_manager_work_date", "manager_workday_snapshots", ["manager_id", "work_date"])

    op.create_table(
        "manager_workdays",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status_raw", sa.String(length=64), nullable=True),
        sa.Column("status_normalized", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("time_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_finish", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("time_leaks_seconds", sa.Integer(), nullable=True),
        sa.Column("source_timezone", sa.String(length=64), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("has_bitrix_timestamps", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manager_id", "work_date", name="uq_manager_workdays_manager_date"),
    )
    op.create_index("ix_manager_workdays_manager_id", "manager_workdays", ["manager_id"])
    op.create_index("ix_mw_work_date", "manager_workdays", ["work_date"])


def downgrade() -> None:
    op.drop_index("ix_mw_work_date", table_name="manager_workdays")
    op.drop_index("ix_manager_workdays_manager_id", table_name="manager_workdays")
    op.drop_table("manager_workdays")
    op.drop_index("ix_mws_manager_work_date", table_name="manager_workday_snapshots")
    op.drop_index("ix_mws_manager_observed", table_name="manager_workday_snapshots")
    op.drop_index("ix_manager_workday_snapshots_work_date", table_name="manager_workday_snapshots")
    op.drop_index("ix_manager_workday_snapshots_bitrix_user_id", table_name="manager_workday_snapshots")
    op.drop_index("ix_manager_workday_snapshots_manager_id", table_name="manager_workday_snapshots")
    op.drop_table("manager_workday_snapshots")
