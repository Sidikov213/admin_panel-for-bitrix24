from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AvitoChat(TimestampMixin, Base):
    """A dialog of one of our Avito accounts with a client (Messenger API)."""

    __tablename__ = "avito_chats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chat_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    item_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    client_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Derived from messages: first client message, first reply after it, last message
    first_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    messages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Link to the Bitrix deal: the chat id/link found in the deal fields or comments
    deal_bitrix_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    deal_link_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (Index("ix_avito_chats_account_created", "account_id", "created"),)


class AvitoMessage(Base):
    __tablename__ = "avito_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # in = from the client to us, out = from us (manager or auto-reply)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    author_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    msg_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_avito_messages_chat_created", "chat_id", "created"),)
