"""stage SLA rules; activity last_updated; reset wrong completed_at

Revision ID: 20261103_0005
Revises: 20261102_0004
Create Date: 2026-11-03

completed_at used to hold END_TIME (the planned end, not the completion moment).
It is cleared here and refilled from LAST_UPDATED by the next full activity sync.
Idempotent: 0001 builds tables from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261103_0005"
down_revision: Union[str, None] = "20261102_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "last_updated" not in {c["name"] for c in insp.get_columns("crm_activities")}:
        op.add_column("crm_activities", sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True))
        # Only when upgrading an existing database: its completed_at values are END_TIME
        op.execute("UPDATE crm_activities SET completed_at = NULL")
    if "stage_sla_rules" not in insp.get_table_names():
        op.create_table(
            "stage_sla_rules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("stage_bitrix_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("threshold", sa.Numeric(10, 2), nullable=True),
            sa.Column("unit", sa.String(length=16), nullable=False, server_default="calendar_days"),
            sa.Column("reaction_stage", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "stage_sla_rules" in insp.get_table_names():
        op.drop_table("stage_sla_rules")
    if "last_updated" in {c["name"] for c in insp.get_columns("crm_activities")}:
        op.drop_column("crm_activities", "last_updated")
