"""CRUD + schedule resolution for Manager Control V3."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_schedules import (
    CalendarDayOverride,
    ManagerAbsence,
    ManagerControlPolicy,
    ScheduleAssignment,
    WorkSchedule,
)
from app.services.workday_rules import ScheduleSpec, build_day_plan


def schedule_to_spec(row: WorkSchedule) -> ScheduleSpec:
    weekdays = row.weekdays if isinstance(row.weekdays, list) else []
    return ScheduleSpec(
        id=row.id,
        name=row.name,
        timezone=row.timezone or "Europe/Moscow",
        weekdays=[int(x) for x in weekdays],
        start_time=row.start_time,
        end_time=row.end_time,
        required_minutes=row.required_minutes,
        late_grace_minutes=row.late_grace_minutes,
        early_finish_grace_minutes=row.early_finish_grace_minutes,
        max_break_minutes=row.max_break_minutes,
        not_started_threshold_minutes=row.not_started_threshold_minutes,
        not_closed_grace_minutes=row.not_closed_grace_minutes,
        enabled=bool(row.enabled),
    )


def schedule_to_dict(row: WorkSchedule) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "timezone": row.timezone,
        "weekdays": row.weekdays,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "required_minutes": row.required_minutes,
        "late_grace_minutes": row.late_grace_minutes,
        "early_finish_grace_minutes": row.early_finish_grace_minutes,
        "max_break_minutes": row.max_break_minutes,
        "not_started_threshold_minutes": row.not_started_threshold_minutes,
        "not_closed_grace_minutes": row.not_closed_grace_minutes,
        "enabled": row.enabled,
        "is_default": row.is_default,
        "note": row.note,
    }


async def list_schedules(session: AsyncSession) -> list[WorkSchedule]:
    return list(
        (await session.execute(select(WorkSchedule).order_by(WorkSchedule.id.asc()))).scalars().all()
    )


async def get_schedule(session: AsyncSession, schedule_id: int) -> WorkSchedule | None:
    return await session.get(WorkSchedule, schedule_id)


async def create_schedule(session: AsyncSession, data: dict[str, Any]) -> WorkSchedule:
    if data.get("is_default"):
        await _clear_defaults(session)
    row = WorkSchedule(
        name=str(data["name"]),
        timezone=str(data.get("timezone") or "Europe/Moscow"),
        weekdays=list(data.get("weekdays") or []),
        start_time=str(data["start_time"]),
        end_time=str(data["end_time"]),
        required_minutes=data.get("required_minutes"),
        late_grace_minutes=data.get("late_grace_minutes"),
        early_finish_grace_minutes=data.get("early_finish_grace_minutes"),
        max_break_minutes=data.get("max_break_minutes"),
        not_started_threshold_minutes=data.get("not_started_threshold_minutes"),
        not_closed_grace_minutes=data.get("not_closed_grace_minutes"),
        enabled=bool(data.get("enabled", True)),
        is_default=bool(data.get("is_default", False)),
        note=data.get("note"),
    )
    session.add(row)
    await session.flush()
    return row


async def update_schedule(session: AsyncSession, schedule_id: int, data: dict[str, Any]) -> WorkSchedule:
    row = await get_schedule(session, schedule_id)
    if row is None:
        raise ValueError("schedule_not_found")
    if data.get("is_default"):
        await _clear_defaults(session, except_id=schedule_id)
    for key in (
        "name",
        "timezone",
        "weekdays",
        "start_time",
        "end_time",
        "required_minutes",
        "late_grace_minutes",
        "early_finish_grace_minutes",
        "max_break_minutes",
        "not_started_threshold_minutes",
        "not_closed_grace_minutes",
        "enabled",
        "is_default",
        "note",
    ):
        if key in data:
            setattr(row, key, data[key])
    await session.flush()
    return row


async def delete_schedule(session: AsyncSession, schedule_id: int) -> None:
    row = await get_schedule(session, schedule_id)
    if row is None:
        raise ValueError("schedule_not_found")
    await session.delete(row)
    await session.flush()


async def _clear_defaults(session: AsyncSession, *, except_id: int | None = None) -> None:
    rows = (await session.execute(select(WorkSchedule).where(WorkSchedule.is_default.is_(True)))).scalars().all()
    for r in rows:
        if except_id is not None and r.id == except_id:
            continue
        r.is_default = False


async def resolve_schedule_for_manager(
    session: AsyncSession,
    manager_id: int,
    *,
    department_key: str | None = None,
) -> WorkSchedule | None:
    """Priority: manager override → department_key → is_default → None."""
    mgr_asg = (
        await session.execute(
            select(ScheduleAssignment).where(ScheduleAssignment.manager_id == manager_id)
        )
    ).scalar_one_or_none()
    if mgr_asg is not None:
        sch = await get_schedule(session, mgr_asg.schedule_id)
        if sch and sch.enabled:
            return sch

    if department_key is None:
        from app.models.crm import CrmManager
        manager = await session.get(CrmManager, manager_id)
        departments = (manager.raw or {}).get("UF_DEPARTMENT", []) if manager else []
        if not isinstance(departments, list):
            departments = [departments]
        # Bitrix primary department is first; manager override still has priority.
        department_key = str(departments[0]) if departments else None
    if department_key:
        dept_asg = (
            await session.execute(
                select(ScheduleAssignment).where(
                    ScheduleAssignment.department_key == department_key,
                    ScheduleAssignment.manager_id.is_(None),
                )
            )
        ).scalars().first()
        if dept_asg is not None:
            sch = await get_schedule(session, dept_asg.schedule_id)
            if sch and sch.enabled:
                return sch

    default = (
        await session.execute(
            select(WorkSchedule).where(
                WorkSchedule.is_default.is_(True),
                WorkSchedule.enabled.is_(True),
            )
        )
    ).scalars().first()
    return default


async def get_or_create_policy(session: AsyncSession, *, create: bool = False) -> ManagerControlPolicy:
    row = await session.get(ManagerControlPolicy, 1)
    if row is None:
        row = ManagerControlPolicy(id=1)
        if create:
            session.add(row)
            await session.flush()
    return row


async def absence_kind_on(
    session: AsyncSession, manager_id: int, day: date
) -> str | None:
    row = (
        await session.execute(
            select(ManagerAbsence).where(
                ManagerAbsence.manager_id == manager_id,
                ManagerAbsence.date_from <= day,
                ManagerAbsence.date_to >= day,
            )
        )
    ).scalars().first()
    return row.kind if row else None


async def calendar_overrides_for(
    session: AsyncSession, day: date, manager_id: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rows = (
        await session.execute(
            select(CalendarDayOverride).where(CalendarDayOverride.day_date == day)
        )
    ).scalars().all()
    global_o = None
    mgr_o = None
    for r in rows:
        payload = {
            "kind": r.kind,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "required_minutes": r.required_minutes,
            "label": r.label,
        }
        if r.manager_id is None:
            global_o = payload
        elif r.manager_id == manager_id:
            mgr_o = payload
    return global_o, mgr_o


async def resolve_day_plan_for_manager(
    session: AsyncSession,
    manager_id: int,
    day: date,
    *,
    department_key: str | None = None,
):
    sch = await resolve_schedule_for_manager(session, manager_id, department_key=department_key)
    if sch is None:
        return None, None
    global_o, mgr_o = await calendar_overrides_for(session, day, manager_id)
    absence = await absence_kind_on(session, manager_id, day)
    plan = build_day_plan(
        schedule_to_spec(sch),
        day=day,
        global_override=global_o,
        manager_override=mgr_o,
        absence_kind=absence,
    )
    return sch, plan


class ReportPlans:
    """Request-local schedule data; a report does not query per manager per day."""

    @classmethod
    async def load(cls, session: AsyncSession, start: date, end: date):
        from app.models.crm import CrmManager
        obj = cls()
        obj.schedules = {r.id: r for r in await list_schedules(session) if r.enabled}
        obj.assignments = (await session.execute(select(ScheduleAssignment).order_by(ScheduleAssignment.id))).scalars().all()
        obj.managers = {r.id: r for r in (await session.execute(select(CrmManager))).scalars().all()}
        obj.overrides = (await session.execute(select(CalendarDayOverride).where(
            CalendarDayOverride.day_date.between(start, end)
        ).order_by(CalendarDayOverride.id))).scalars().all()
        obj.absences = (await session.execute(select(ManagerAbsence).where(
            ManagerAbsence.date_from <= end, ManagerAbsence.date_to >= start
        ).order_by(ManagerAbsence.id))).scalars().all()
        return obj

    def resolve(self, manager_id: int, day: date):
        manager = self.managers.get(manager_id)
        departments = (manager.raw or {}).get("UF_DEPARTMENT", []) if manager else []
        if not isinstance(departments, list):
            departments = [departments]
        department = str(departments[0]) if departments else None
        personal = [a for a in self.assignments if a.manager_id == manager_id]
        group = [a for a in self.assignments if a.manager_id is None and department and a.department_key == department]
        sch = next((self.schedules[a.schedule_id] for a in personal + group if a.schedule_id in self.schedules), None)
        if sch is None:
            sch = next((s for s in self.schedules.values() if s.is_default), None)
        if sch is None:
            return None, None
        overrides = {r.manager_id: {k: getattr(r, k) for k in ("kind", "start_time", "end_time", "required_minutes", "label")}
                     for r in self.overrides if r.day_date == day}
        absence = next((a.kind for a in self.absences if a.manager_id == manager_id and a.date_from <= day <= a.date_to), None)
        return sch, build_day_plan(schedule_to_spec(sch), day=day,
            global_override=overrides.get(None), manager_override=overrides.get(manager_id), absence_kind=absence)
