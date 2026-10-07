import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    viewer = "viewer"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_sessions_user_expires", "user_id", "expires_at"),)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_login_attempts_ip_email_at", "ip", "email", "attempted_at"),)
