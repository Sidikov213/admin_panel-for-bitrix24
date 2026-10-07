from datetime import date

from sqlalchemy import Date, ForeignKey, Index, UniqueConstraint
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
