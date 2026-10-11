"""Local Timeman workday history (Focus Analytics — not Bitrix historical import)."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class ManagerWorkdaySnapshot(TimestampMixin, Base):
    """Point-in-time observation from timeman.status (READ ONLY).

    observed_at = when Focus Analytics polled Bitrix — not a user action timestamp.
    time_start / time_finish = Bitrix timestamps when present.
    """

    __tablename__ = "manager_workday_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bitrix_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    status_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_normalized: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    time_leaks_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_leaks_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)

    source_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tz_offset_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    manager = relationship("CrmManager")

    __table_args__ = (
        Index("ix_mws_manager_observed", "manager_id", "observed_at"),
        Index("ix_mws_manager_work_date", "manager_id", "work_date"),
        # Dedup identical payloads for the same manager (skip re-insert of same state)
        UniqueConstraint("manager_id", "content_hash", name="uq_mws_manager_content_hash"),
    )


class ManagerWorkday(TimestampMixin, Base):
    """Aggregated local workday row (one per manager per calendar day in app TZ)."""

    __tablename__ = "manager_workdays"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)

    status_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_normalized: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_leaks_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    has_bitrix_timestamps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    manager = relationship("CrmManager")

    __table_args__ = (
        UniqueConstraint("manager_id", "work_date", name="uq_manager_workdays_manager_date"),
        Index("ix_mw_work_date", "work_date"),
    )


class MonitoredManager(TimestampMixin, Base):
    """Sales Manager Control roster — independent of Bitrix user ACTIVE flag.

    Auto-included when manager appears on deals in synced categories (or activities
    on those deals). Admin may force include/exclude.
    """

    __tablename__ = "monitored_managers"

    manager_id: Mapped[int] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), primary_key=True
    )
    auto_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_include: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_exclude: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    manager = relationship("CrmManager")
