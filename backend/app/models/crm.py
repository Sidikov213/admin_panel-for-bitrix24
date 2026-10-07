from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class CrmManager(TimestampMixin, Base):
    __tablename__ = "crm_managers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bitrix_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    deals: Mapped[list["CrmDeal"]] = relationship(back_populates="assigned_manager")


class CrmPipeline(TimestampMixin, Base):
    __tablename__ = "crm_pipelines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bitrix_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    stages: Mapped[list["CrmStage"]] = relationship(back_populates="pipeline")


class CrmStage(TimestampMixin, Base):
    __tablename__ = "crm_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bitrix_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("crm_pipelines.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # semantics: success | failure | process | etc. — from Bitrix STAGE_SEMANTIC_ID when present
    semantics: Mapped[str | None] = mapped_column(String(32), nullable=True)

    pipeline: Mapped[CrmPipeline] = relationship(back_populates="stages")
    deals: Mapped[list["CrmDeal"]] = relationship(back_populates="stage")

    __table_args__ = (Index("ix_crm_stages_pipeline_sort", "pipeline_id", "sort"),)


class CrmDeal(TimestampMixin, Base):
    __tablename__ = "crm_deals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bitrix_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("crm_stages.id", ondelete="SET NULL"), nullable=True)
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="SET NULL"), nullable=True
    )
    opportunity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    date_create: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_modify: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closedate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_changed_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_future_activity: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_activities_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Set during full reconcile when Bitrix no longer returns the deal in synced categories
    missing_from_bitrix: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    missing_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stage: Mapped[CrmStage | None] = relationship(back_populates="deals")
    assigned_manager: Mapped[CrmManager | None] = relationship(back_populates="deals")
    snapshots: Mapped[list["DealSnapshot"]] = relationship(back_populates="deal")
    change_events: Mapped[list["DealChangeEvent"]] = relationship(back_populates="deal")

    __table_args__ = (
        Index("ix_crm_deals_stage_closed", "stage_id", "closed"),
        Index("ix_crm_deals_assigned_closed", "assigned_by_id", "closed"),
        Index("ix_crm_deals_date_create", "date_create"),
        Index("ix_crm_deals_closed_missing", "closed", "missing_from_bitrix"),
        Index("ix_crm_deals_active_no_future", "closed", "has_future_activity", "missing_from_bitrix"),
    )


class CrmActivity(TimestampMixin, Base):
    __tablename__ = "crm_activities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bitrix_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    responsible_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_crm_activities_owner_completed", "owner_id", "completed"),
        Index("ix_crm_activities_open_deadline", "completed", "deadline"),
    )


class DealSnapshot(TimestampMixin, Base):
    __tablename__ = "deal_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    deal: Mapped[CrmDeal] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("deal_id", "content_hash", name="uq_deal_snapshots_deal_hash"),
        Index("ix_deal_snapshots_deal_observed", "deal_id", "observed_at"),
    )


class DealChangeEvent(Base):
    __tablename__ = "deal_change_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bitrix_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deal: Mapped[CrmDeal] = relationship(back_populates="change_events")

    __table_args__ = (Index("ix_deal_change_events_deal_observed", "deal_id", "observed_at"),)
