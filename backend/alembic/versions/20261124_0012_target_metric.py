"""sales_targets.metric: a plan in revenue or in profit

Revision ID: 20261124_0012
Revises: 20261119_0011
Create Date: 2026-11-24

Idempotent: 0001 builds tables from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261124_0012"
down_revision: Union[str, None] = "20261119_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("sales_targets")}
    if "metric" in columns:
        return
    op.add_column("sales_targets", sa.Column("metric", sa.String(16), nullable=False, server_default="revenue"))


def downgrade() -> None:
    op.drop_column("sales_targets", "metric")
