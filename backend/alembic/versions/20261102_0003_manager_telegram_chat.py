"""manager telegram_chat_id for daily digest

Revision ID: 20261102_0003
Revises: 20251006_0002
Create Date: 2026-11-02

Idempotent: 0001 builds tables from current models, so a fresh database
already has the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261102_0003"
down_revision: Union[str, None] = "20251006_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns(table)}
    return column in cols


def upgrade() -> None:
    if not _has_column("crm_managers", "telegram_chat_id"):
        op.add_column("crm_managers", sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _has_column("crm_managers", "telegram_chat_id"):
        op.drop_column("crm_managers", "telegram_chat_id")
