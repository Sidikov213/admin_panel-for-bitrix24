"""crm_deals.is_excluded: deals taken out of the analytics in the panel

Revision ID: 20261119_0011
Revises: 20261116_0010
Create Date: 2026-11-19

Idempotent: 0001 builds tables from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261119_0011"
down_revision: Union[str, None] = "20261116_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("crm_deals")}
    if "is_excluded" in columns:
        return
    op.add_column("crm_deals", sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("crm_deals", "is_excluded")
