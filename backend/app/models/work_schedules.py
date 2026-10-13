"""Manager Control V3 — configurable work schedules, calendar, violations."""

from datetime import date, datetime

from sqlalchemy import (
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


class WorkSchedule(TimestampMixin, Base):
    """Configurable work schedule. No company defaults baked into code."""

    __tablename__ = "work_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    # ISO weekdays 1=Mon .. 7=Sun
    weekdays: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    start_time: Mapped[str] = mapped_column(String(8), nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String(8), nullable=False)
    required_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_finish_grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Minutes after scheduled start before WORKDAY_NOT_STARTED may fire
    not_started_threshold_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Minutes after scheduled end before WORKDAY_NOT_CLOSED may fire
    not_closed_grace_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScheduleAssignment(TimestampMixin, Base):
    """Assign schedule to a manager (override) or department_key (group default).

    Resolution priority: manager override → department_key → schedule.is_default → none.
    """

    __tablename__ = "schedule_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("work_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    department_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    schedule = relationship("WorkSchedule")
    manager = relationship("CrmManager")

    __table_args__ = (
        Index("ix_schedule_assign_dept", "department_key"),
    )


class CalendarDayOverride(TimestampMixin, Base):
    """Local business calendar override for a date (global or per-manager)."""

    __tablename__ = "calendar_day_overrides"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # working | weekend | holiday | shortened | day_off
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    start_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    required_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("day_date", "manager_id", name="uq_calendar_day_manager"),
    )


class ManagerAbsence(TimestampMixin, Base):
    """Manual absence range (vacation / sick / day off)."""

    __tablename__ = "manager_absences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    # day_off | vacation | sick | absence
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="absence")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_manager_absence_range", "manager_id", "date_from", "date_to"),)


class WorkdayViolation(TimestampMixin, Base):
    """Stateful workday violation — one row per manager+date+type."""

    __tablename__ = "workday_violations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("crm_managers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    violation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # OPEN | RESOLVED
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    # INFO | WARNING | HIGH
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="WARNING")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    threshold_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_schedules.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # True when detected before enforcement_start_date (preview-only)
    is_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "manager_id", "work_date", "violation_type", name="uq_workday_violation_occurrence"
        ),
        Index("ix_wv_state_date", "state", "work_date"),
    )


class ManagerControlPolicy(TimestampMixin, Base):
    """Singleton policy row (id=1): enforcement date + severity map."""

    __tablename__ = "manager_control_policy"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    enforcement_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Optional map violation_type → INFO|WARNING|HIGH
    severity_by_type: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
