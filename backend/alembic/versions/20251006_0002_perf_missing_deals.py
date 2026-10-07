"""perf indexes + missing_from_bitrix

Revision ID: 20251006_0002
Revises: 20251006_0001
Create Date: 2026-10-06

Idempotent: initial schema may already include missing_* columns/indexes
when Stage-1 hardening was folded into 0001.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20251006_0002"
down_revision: Union[str, None] = "20251006_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    return column in cols


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    idx = {i["name"] for i in inspect(bind).get_indexes(table)}
    return name in idx


def upgrade() -> None:
    if not _has_column("crm_deals", "missing_from_bitrix"):
        op.add_column(
            "crm_deals",
            sa.Column("missing_from_bitrix", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if not _has_column("crm_deals", "missing_observed_at"):
        op.add_column(
            "crm_deals",
            sa.Column("missing_observed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_index("crm_deals", "ix_crm_deals_missing_from_bitrix"):
        op.create_index("ix_crm_deals_missing_from_bitrix", "crm_deals", ["missing_from_bitrix"])
    if not _has_index("crm_deals", "ix_crm_deals_date_create"):
        op.create_index("ix_crm_deals_date_create", "crm_deals", ["date_create"])
    if not _has_index("crm_deals", "ix_crm_deals_closed_missing"):
        op.create_index("ix_crm_deals_closed_missing", "crm_deals", ["closed", "missing_from_bitrix"])
    if not _has_index("crm_deals", "ix_crm_deals_active_no_future"):
        op.create_index(
            "ix_crm_deals_active_no_future",
            "crm_deals",
            ["closed", "has_future_activity", "missing_from_bitrix"],
        )
    if not _has_index("crm_activities", "ix_crm_activities_open_deadline"):
        op.create_index("ix_crm_activities_open_deadline", "crm_activities", ["completed", "deadline"])
    if not _has_index("deal_change_events", "ix_deal_change_events_observed_at"):
        op.create_index("ix_deal_change_events_observed_at", "deal_change_events", ["observed_at"])


def downgrade() -> None:
    if _has_index("deal_change_events", "ix_deal_change_events_observed_at"):
        op.drop_index("ix_deal_change_events_observed_at", table_name="deal_change_events")
    if _has_index("crm_activities", "ix_crm_activities_open_deadline"):
        op.drop_index("ix_crm_activities_open_deadline", table_name="crm_activities")
    if _has_index("crm_deals", "ix_crm_deals_active_no_future"):
        op.drop_index("ix_crm_deals_active_no_future", table_name="crm_deals")
    if _has_index("crm_deals", "ix_crm_deals_closed_missing"):
        op.drop_index("ix_crm_deals_closed_missing", table_name="crm_deals")
    if _has_index("crm_deals", "ix_crm_deals_date_create"):
        op.drop_index("ix_crm_deals_date_create", table_name="crm_deals")
    if _has_index("crm_deals", "ix_crm_deals_missing_from_bitrix"):
        op.drop_index("ix_crm_deals_missing_from_bitrix", table_name="crm_deals")
    # Do not drop columns if they belong to initial schema on this branch.
