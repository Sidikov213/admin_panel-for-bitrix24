"""manager control monitored roster

Revision ID: 20261007_0006
Revises: 20261007_0005
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0006"
down_revision: Union[str, None] = "20261007_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitored_managers",
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("auto_included", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("manual_include", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("manual_exclude", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_reason", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("manager_id"),
    )
    op.create_index("ix_monitored_managers_auto_included", "monitored_managers", ["auto_included"])
    op.create_index("ix_monitored_managers_manual_include", "monitored_managers", ["manual_include"])


def downgrade() -> None:
    op.drop_index("ix_monitored_managers_manual_include", table_name="monitored_managers")
    op.drop_index("ix_monitored_managers_auto_included", table_name="monitored_managers")
    op.drop_table("monitored_managers")
