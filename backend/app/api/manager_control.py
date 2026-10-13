from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.csrf import validate_csrf
from app.auth.deps import AdminUser, CurrentUser, DbSession
from app.services import manager_control_service as svc
from app.services import mc_reports
from app.services import monitored_roster as roster
from app.services import schedule_service as schedules
from app.services.violation_evaluator import preview_schedule_last_days
from app.models.work_schedules import (
    CalendarDayOverride,
    ManagerAbsence,
    ScheduleAssignment,
)

router = APIRouter()

CsrfHeader = Annotated[str | None, Header(alias="X-CSRF-Token")]


class RosterPatch(BaseModel):
    include: bool | None = None
    exclude: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class ScheduleIn(BaseModel):
    name: str
    timezone: str = "Europe/Moscow"
    weekdays: list[int] = Field(default_factory=list)
    start_time: str
    end_time: str
    required_minutes: int | None = None
    late_grace_minutes: int | None = None
    early_finish_grace_minutes: int | None = None
    max_break_minutes: int | None = None
    not_started_threshold_minutes: int | None = None
    not_closed_grace_minutes: int | None = None
    enabled: bool = True
    is_default: bool = False
    note: str | None = None


class AssignmentIn(BaseModel):
    schedule_id: int
    manager_id: int | None = None
    department_key: str | None = None
    note: str | None = None


class CalendarIn(BaseModel):
    day_date: date
    kind: str
    manager_id: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    required_minutes: int | None = None
    label: str | None = None
    note: str | None = None


class AbsenceIn(BaseModel):
    manager_id: int
    date_from: date
    date_to: date
    kind: str = "absence"
    note: str | None = None


class PolicyIn(BaseModel):
    enforcement_start_date: date | None = None
    severity_by_type: dict[str, str] | None = None
    note: str | None = None


# --- board / detail (existing) ---


@router.get("")
async def manager_control_list(_user: CurrentUser, db: DbSession) -> dict:
    return await svc.list_manager_control(db)


@router.get("/report")
async def team_report(
    _user: CurrentUser,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    period: str | None = Query(default="week"),
) -> dict:
    from datetime import timedelta

    from app.core.timezone import app_tz, utc_now

    today = utc_now().astimezone(app_tz()).date()
    if start and end:
        s, e = start, end
    elif period == "month":
        s = today.replace(day=1)
        e = today
    else:
        s = today - timedelta(days=today.weekday())
        e = s + timedelta(days=6)
    return await mc_reports.team_report(db, start=s, end=e)


@router.get("/report.csv")
async def team_report_csv(
    _user: CurrentUser,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
) -> Response:
    from datetime import timedelta

    from app.core.timezone import app_tz, utc_now

    today = utc_now().astimezone(app_tz()).date()
    if not start or not end:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    data = await mc_reports.team_report(db, start=start, end=end)
    lines = [",".join(data["csv_headers"])]
    for it in data["items"]:
        lines.append(
            ",".join(
                [
                    f"\"{it['display_name']}\"",
                    str(it["working_days_plan"]),
                    str(it["marked_days"]),
                    str(it["plan_minutes"]),
                    str(it["fact_seconds"]),
                    str(it["delta_minutes"]),
                    str(it["late_starts"]),
                    str(it["not_closed"]),
                    str(it["open_violations"]),
                    str(it["crm_actions"]),
                ]
            )
        )
    body = "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=manager-control-report.csv"},
    )


@router.get("/roster")
async def manager_control_roster(_admin: AdminUser, db: DbSession) -> dict:
    items = await roster.list_roster_admin(db)
    return {"items": items, "total": len(items)}


@router.patch("/roster/{manager_id}")
async def patch_manager_roster(
    manager_id: int,
    body: RosterPatch,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    try:
        row = await roster.set_manual_monitor(
            db,
            manager_id,
            include=body.include,
            exclude=body.exclude,
            note=body.note,
        )
        await db.commit()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found") from None
    return {
        "manager_id": row.manager_id,
        "manual_include": row.manual_include,
        "manual_exclude": row.manual_exclude,
        "auto_included": row.auto_included,
        "monitored": roster.is_monitored_row(row),
        "note": row.note,
    }


# --- admin: schedules ---


@router.get("/admin/schedules")
async def admin_list_schedules(_admin: AdminUser, db: DbSession) -> dict:
    rows = await schedules.list_schedules(db)
    return {"items": [schedules.schedule_to_dict(r) for r in rows], "total": len(rows)}


@router.post("/admin/schedules")
async def admin_create_schedule(
    body: ScheduleIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = await schedules.create_schedule(db, body.model_dump())
    await db.commit()
    return schedules.schedule_to_dict(row)


@router.patch("/admin/schedules/{schedule_id}")
async def admin_update_schedule(
    schedule_id: int,
    body: ScheduleIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    try:
        row = await schedules.update_schedule(db, schedule_id, body.model_dump())
        await db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Schedule not found") from None
    return schedules.schedule_to_dict(row)


@router.delete("/admin/schedules/{schedule_id}")
async def admin_delete_schedule(
    schedule_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    try:
        await schedules.delete_schedule(db, schedule_id)
        await db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Schedule not found") from None
    return {"ok": True}


@router.get("/admin/assignments")
async def admin_list_assignments(_admin: AdminUser, db: DbSession) -> dict:
    rows = (await db.execute(select(ScheduleAssignment).order_by(ScheduleAssignment.id))).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "schedule_id": r.schedule_id,
                "manager_id": r.manager_id,
                "department_key": r.department_key,
                "note": r.note,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/admin/assignments")
async def admin_create_assignment(
    body: AssignmentIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    if body.manager_id is None and not body.department_key:
        raise HTTPException(status_code=400, detail="manager_id or department_key required")
    if await schedules.get_schedule(db, body.schedule_id) is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if body.manager_id is not None:
        existing = (
            await db.execute(
                select(ScheduleAssignment).where(ScheduleAssignment.manager_id == body.manager_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.schedule_id = body.schedule_id
            existing.note = body.note
            await db.commit()
            return {
                "id": existing.id,
                "schedule_id": existing.schedule_id,
                "manager_id": existing.manager_id,
                "department_key": existing.department_key,
            }
    row = ScheduleAssignment(
        schedule_id=body.schedule_id,
        manager_id=body.manager_id,
        department_key=body.department_key,
        note=body.note,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "schedule_id": row.schedule_id,
        "manager_id": row.manager_id,
        "department_key": row.department_key,
    }


@router.delete("/admin/assignments/{assignment_id}")
async def admin_delete_assignment(
    assignment_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = await db.get(ScheduleAssignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.get("/admin/calendar")
async def admin_list_calendar(
    _admin: AdminUser,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    q = select(CalendarDayOverride).order_by(CalendarDayOverride.day_date.desc())
    if start:
        q = q.where(CalendarDayOverride.day_date >= start)
    if end:
        q = q.where(CalendarDayOverride.day_date <= end)
    rows = (await db.execute(q.limit(500))).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "day_date": r.day_date.isoformat(),
                "kind": r.kind,
                "manager_id": r.manager_id,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "required_minutes": r.required_minutes,
                "label": r.label,
                "note": r.note,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/admin/calendar")
async def admin_upsert_calendar(
    body: CalendarIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    existing = (
        await db.execute(
            select(CalendarDayOverride).where(
                CalendarDayOverride.day_date == body.day_date,
                (
                    CalendarDayOverride.manager_id == body.manager_id
                    if body.manager_id is not None
                    else CalendarDayOverride.manager_id.is_(None)
                ),
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.kind = body.kind
        existing.start_time = body.start_time
        existing.end_time = body.end_time
        existing.required_minutes = body.required_minutes
        existing.label = body.label
        existing.note = body.note
        row = existing
    else:
        row = CalendarDayOverride(**body.model_dump())
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "day_date": row.day_date.isoformat(), "kind": row.kind}


@router.delete("/admin/calendar/{override_id}")
async def admin_delete_calendar(
    override_id: int,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = await db.get(CalendarDayOverride, override_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/admin/absences")
async def admin_create_absence(
    body: AbsenceIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    row = ManagerAbsence(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "manager_id": row.manager_id,
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "kind": row.kind,
    }


@router.get("/admin/policy")
async def admin_get_policy(_admin: AdminUser, db: DbSession) -> dict:
    policy = await schedules.get_or_create_policy(db)
    await db.commit()
    return {
        "enforcement_start_date": (
            policy.enforcement_start_date.isoformat() if policy.enforcement_start_date else None
        ),
        "severity_by_type": policy.severity_by_type or {},
        "note": policy.note,
    }


@router.patch("/admin/policy")
async def admin_patch_policy(
    body: PolicyIn,
    _admin: AdminUser,
    db: DbSession,
    request: Request,
    csrf_header: CsrfHeader = None,
) -> dict:
    validate_csrf(request, csrf_header)
    policy = await schedules.get_or_create_policy(db)
    data = body.model_dump(exclude_unset=True)
    if "enforcement_start_date" in data:
        policy.enforcement_start_date = data["enforcement_start_date"]
    if "severity_by_type" in data:
        policy.severity_by_type = data["severity_by_type"]
    if "note" in data:
        policy.note = data["note"]
    await db.commit()
    return {
        "enforcement_start_date": (
            policy.enforcement_start_date.isoformat() if policy.enforcement_start_date else None
        ),
        "severity_by_type": policy.severity_by_type or {},
        "note": policy.note,
    }


@router.get("/admin/preview")
async def admin_preview(
    _admin: AdminUser,
    db: DbSession,
    schedule_id: int,
    manager_id: int,
    days: int = Query(default=7, ge=1, le=31),
) -> dict:
    try:
        return await preview_schedule_last_days(db, schedule_id, manager_id, days=days)
    except ValueError:
        raise HTTPException(status_code=404, detail="Schedule not found") from None


@router.get("/{manager_id}/week")
async def manager_week(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
    anchor: date | None = None,
) -> dict:
    return await mc_reports.week_report(db, manager_id, anchor=anchor)


@router.get("/{manager_id}/month")
async def manager_month(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    from app.core.timezone import app_tz, utc_now

    today = utc_now().astimezone(app_tz()).date()
    return await mc_reports.month_report(
        db, manager_id, year=year or today.year, month=month or today.month
    )


@router.get("/{manager_id}")
async def manager_control_detail(
    manager_id: int,
    _user: CurrentUser,
    db: DbSession,
) -> dict:
    data = await svc.get_manager_control_detail(db, manager_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    return data
