"""Configurable stalled-deal rules — empty until sales regulation is approved."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class StalledRule(TimestampMixin, Base):
    __tablename__ = "stalled_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Bitrix category id (pipeline); null = any pipeline
    pipeline_bitrix_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Internal stage id; null = any stage
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("crm_stages.id", ondelete="CASCADE"), nullable=True)
    max_idle_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    future_activity_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_next_activity_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional: only apply to open / won / lost — open by default
    deal_status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    # Use business calendar when evaluating durations (not implemented until rules enabled)
    use_business_calendar: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
