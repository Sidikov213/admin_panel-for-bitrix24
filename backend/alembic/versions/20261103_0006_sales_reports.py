"""sales_reports archive (daily / weekly / monthly reports)

Revision ID: 20261103_0006
Revises: 20261103_0005
Create Date: 2026-11-03

Idempotent: 0001 builds tables from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261103_0006"
down_revision: Union[str, None] = "20261103_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "sales_reports" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "sales_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_to", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "period_start", "period_end", name="uq_sales_reports_period"),
    )
    op.create_index("ix_sales_reports_kind_start", "sales_reports", ["kind", "period_start"])


def downgrade() -> None:
    if "sales_reports" in inspect(op.get_bind()).get_table_names():
        op.drop_table("sales_reports")
