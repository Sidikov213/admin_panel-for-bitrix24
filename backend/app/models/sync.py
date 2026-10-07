import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin
from app.models.targets import PeriodType


class SyncType(str, enum.Enum):
    dictionaries = "dictionaries"
    deals = "deals"
    activities = "activities"
    full_reconcile = "full_reconcile"


class SyncStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sync_type: Mapped[SyncType] = mapped_column(Enum(SyncType, name="sync_type"), nullable=False, index=True)
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, name="sync_status"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SalesTarget(TimestampMixin, Base):
    __tablename__ = "sales_targets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("crm_managers.id", ondelete="SET NULL"), nullable=True)
    period_type: Mapped[PeriodType] = mapped_column(Enum(PeriodType, name="period_type"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")

    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "period_type",
            "period_start",
            "period_end",
            name="uq_sales_targets_period",
        ),
    )
