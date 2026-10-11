"""Configurable sales rules + violation state + audit trail."""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class RuleSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ViolationStatus(str, Enum):
    open = "open"
    resolved = "resolved"


class ViolationType(str, Enum):
    NO_FUTURE_ACTIVITY = "NO_FUTURE_ACTIVITY"
    OVERDUE_ACTIVITY = "OVERDUE_ACTIVITY"
    IDLE_TOO_LONG = "IDLE_TOO_LONG"
    STAGE_TOO_LONG = "STAGE_TOO_LONG"
    NEXT_ACTIVITY_TOO_FAR = "NEXT_ACTIVITY_TOO_FAR"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    COMMENT_MISSING = "COMMENT_MISSING"
    COMMENT_TOO_OLD = "COMMENT_TOO_OLD"


class SalesRule(TimestampMixin, Base):
    __tablename__ = "sales_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Bitrix category id; null = any pipeline
    pipeline_bitrix_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Internal crm_stages.id; null = any stage in pipeline (or global)
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_stages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    max_idle_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    future_activity_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    max_next_activity_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # None = do not enforce as business rule; False = overdue is violation; True = allowed
    overdue_activity_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    required_fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    required_comment: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment_max_age_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_stage_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), default=RuleSeverity.medium.value, nullable=False)

    # Comment checks are a disabled capability until timeline sync exists
    comments_capability: Mapped[str] = mapped_column(
        String(32), default="unsupported", nullable=False
    )

    violations: Mapped[list["SalesRuleViolation"]] = relationship(back_populates="rule")
    audits: Mapped[list["SalesRuleAudit"]] = relationship(back_populates="rule")

    __table_args__ = (Index("ix_sales_rules_pipeline_stage", "pipeline_bitrix_id", "stage_id"),)


class SalesRuleViolation(Base):
    """
    Occurrence model:
    - At most one OPEN row per (deal_id, rule_id, violation_type).
    - When the condition clears → status=RESOLVED, resolved_at set.
    - When the condition returns → a NEW open occurrence is created (history preserved).
    This avoids duplicates per sync cycle while supporting "new during period" reporting.
    """

    __tablename__ = "sales_rule_violations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[int] = mapped_column(ForeignKey("sales_rules.id", ondelete="CASCADE"), nullable=False)
    violation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ViolationStatus.open.value, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    threshold: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Denormalized for fast aggregates
    manager_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    opportunity: Mapped[str | None] = mapped_column(String(64), nullable=True)

    rule: Mapped[SalesRule] = relationship(back_populates="violations")
    deal = relationship("CrmDeal")

    __table_args__ = (
        Index("ix_srv_deal_status", "deal_id", "status"),
        Index("ix_srv_type_status", "violation_type", "status"),
        Index("ix_srv_detected", "detected_at"),
        Index("ix_srv_resolved", "resolved_at"),
        # Partial unique (open only) is created in Alembic for PostgreSQL.
        # SQLite tests use application-level open-map instead of a full unique.
    )


class SalesRuleAudit(Base):
    __tablename__ = "sales_rule_audits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # create|update|delete|enable|disable
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rule: Mapped[SalesRule | None] = relationship(back_populates="audits")


class BitrixDealField(TimestampMixin, Base):
    """READ ONLY metadata from crm.deal.fields for required_fields pickers."""

    __tablename__ = "bitrix_deal_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    field_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_required_in_bitrix: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_multiple: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_user_field: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
