from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AnalyticsDaily(TimestampMixin, Base):
    __tablename__ = "analytics_daily"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    pipeline_id: Mapped[int | None] = mapped_column(ForeignKey("crm_pipelines.id", ondelete="SET NULL"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("crm_managers.id", ondelete="SET NULL"), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("date", "pipeline_id", "manager_id", name="uq_analytics_daily_dims"),
        Index("ix_analytics_daily_date", "date"),
    )


class SalesReport(TimestampMixin, Base):
    """Archived daily / weekly / monthly report (ТЗ §11–12): what was sent and what the panel shows."""

    __tablename__ = "sales_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # daily | weekly | monthly
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Telegram HTML as sent
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_to: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("kind", "period_start", "period_end", name="uq_sales_reports_period"),
        Index("ix_sales_reports_kind_start", "kind", "period_start"),
    )


class AIAnalysis(TimestampMixin, Base):
    """AI conclusion for a period (ТЗ §9–11), with exactly what was sent to the model."""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # daily | weekly | monthly
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # sha256 of the sent context: same numbers → same answer, no second call
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # ok | error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    # Managers appear as «Менеджер-<id>» here; names are put back when shown
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    texts_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # report | manual
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")

    __table_args__ = (Index("ix_ai_analyses_period", "kind", "period_start", "period_end"),)
