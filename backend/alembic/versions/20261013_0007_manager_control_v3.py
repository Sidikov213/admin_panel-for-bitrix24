"""manager control v3 schedules calendar violations

Revision ID: 20261013_0007
Revises: 20261007_0006
Create Date: 2026-10-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0007"
down_revision: Union[str, None] = "20261007_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_schedules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("weekdays", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("start_time", sa.String(length=8), nullable=False),
        sa.Column("end_time", sa.String(length=8), nullable=False),
        sa.Column("required_minutes", sa.Integer(), nullable=True),
        sa.Column("late_grace_minutes", sa.Integer(), nullable=True),
        sa.Column("early_finish_grace_minutes", sa.Integer(), nullable=True),
        sa.Column("max_break_minutes", sa.Integer(), nullable=True),
        sa.Column("not_started_threshold_minutes", sa.Integer(), nullable=True),
        sa.Column("not_closed_grace_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_schedules_is_default", "work_schedules", ["is_default"])

    op.create_table(
        "schedule_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("department_key", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schedule_id"], ["work_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manager_id"),
    )
    op.create_index("ix_schedule_assignments_schedule_id", "schedule_assignments", ["schedule_id"])
    op.create_index("ix_schedule_assign_dept", "schedule_assignments", ["department_key"])

    op.create_table(
        "calendar_day_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.String(length=8), nullable=True),
        sa.Column("end_time", sa.String(length=8), nullable=True),
        sa.Column("required_minutes", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day_date", "manager_id", name="uq_calendar_day_manager"),
    )
    op.create_index("ix_calendar_day_overrides_day_date", "calendar_day_overrides", ["day_date"])
    op.create_index("ix_calendar_day_overrides_manager_id", "calendar_day_overrides", ["manager_id"])

    op.create_table(
        "manager_absences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="absence"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manager_absences_manager_id", "manager_absences", ["manager_id"])
    op.create_index("ix_manager_absence_range", "manager_absences", ["manager_id", "date_from", "date_to"])

    op.create_table(
        "workday_violations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("violation_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="WARNING"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("threshold_value", sa.String(length=64), nullable=True),
        sa.Column("actual_value", sa.String(length=64), nullable=True),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_preview", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["crm_managers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schedule_id"], ["work_schedules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "manager_id", "work_date", "violation_type", name="uq_workday_violation_occurrence"
        ),
    )
    op.create_index("ix_workday_violations_manager_id", "workday_violations", ["manager_id"])
    op.create_index("ix_workday_violations_work_date", "workday_violations", ["work_date"])
    op.create_index("ix_wv_state_date", "workday_violations", ["state", "work_date"])

    op.create_table(
        "manager_control_policy",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("enforcement_start_date", sa.Date(), nullable=True),
        sa.Column("severity_by_type", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("manager_control_policy")
    op.drop_index("ix_wv_state_date", table_name="workday_violations")
    op.drop_index("ix_workday_violations_work_date", table_name="workday_violations")
    op.drop_index("ix_workday_violations_manager_id", table_name="workday_violations")
    op.drop_table("workday_violations")
    op.drop_index("ix_manager_absence_range", table_name="manager_absences")
    op.drop_index("ix_manager_absences_manager_id", table_name="manager_absences")
    op.drop_table("manager_absences")
    op.drop_index("ix_calendar_day_overrides_manager_id", table_name="calendar_day_overrides")
    op.drop_index("ix_calendar_day_overrides_day_date", table_name="calendar_day_overrides")
    op.drop_table("calendar_day_overrides")
    op.drop_index("ix_schedule_assign_dept", table_name="schedule_assignments")
    op.drop_index("ix_schedule_assignments_schedule_id", table_name="schedule_assignments")
    op.drop_table("schedule_assignments")
    op.drop_index("ix_work_schedules_is_default", table_name="work_schedules")
    op.drop_table("work_schedules")
