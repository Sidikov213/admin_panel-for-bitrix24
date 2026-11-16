"""crm_managers.is_tracked: people hidden from the per-manager lists

Revision ID: 20261116_0010
Revises: 20261105_0009
Create Date: 2026-11-16

Idempotent: 0001 builds tables from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261116_0010"
down_revision: Union[str, None] = "20261105_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("crm_managers")}
    if "is_tracked" in columns:
        return
    op.add_column("crm_managers", sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("crm_managers", "is_tracked")
