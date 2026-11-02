"""avito chats and messages; sync_type 'avito'

Revision ID: 20261104_0008
Revises: 20261103_0007
Create Date: 2026-11-04

Idempotent: 0001 builds tables (and the enum) from current models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261104_0008"
down_revision: Union[str, None] = "20261103_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE sync_type ADD VALUE IF NOT EXISTS 'avito'")
    tables = inspect(bind).get_table_names()
    if "avito_chats" not in tables:
        op.create_table(
            "avito_chats",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("chat_id", sa.String(128), nullable=False, unique=True),
            sa.Column("account_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_type", sa.String(16), nullable=True),
            _ts("created"),
            _ts("updated"),
            sa.Column("item_id", sa.BigInteger(), nullable=True),
            sa.Column("item_title", sa.String(512), nullable=True),
            sa.Column("item_url", sa.String(1024), nullable=True),
            sa.Column("client_user_id", sa.BigInteger(), nullable=True),
            sa.Column("client_name", sa.String(255), nullable=True),
            _ts("first_in_at"),
            _ts("first_reply_at"),
            _ts("last_message_at"),
            sa.Column("last_direction", sa.String(8), nullable=True),
            sa.Column("messages_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deal_bitrix_id", sa.BigInteger(), nullable=True),
            sa.Column("deal_link_source", sa.String(16), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_avito_chats_account_id", "avito_chats", ["account_id"])
        op.create_index("ix_avito_chats_item_id", "avito_chats", ["item_id"])
        op.create_index("ix_avito_chats_deal_bitrix_id", "avito_chats", ["deal_bitrix_id"])
        op.create_index("ix_avito_chats_account_created", "avito_chats", ["account_id", "created"])
    if "avito_messages" not in tables:
        op.create_table(
            "avito_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("message_id", sa.String(128), nullable=False, unique=True),
            sa.Column("chat_id", sa.String(128), nullable=False),
            sa.Column("direction", sa.String(8), nullable=False),
            sa.Column("author_id", sa.BigInteger(), nullable=True),
            sa.Column("msg_type", sa.String(32), nullable=True),
            sa.Column("created", sa.DateTime(timezone=True), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_avito_messages_chat_created", "avito_messages", ["chat_id", "created"])


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    for t in ("avito_messages", "avito_chats"):
        if t in tables:
            op.drop_table(t)
