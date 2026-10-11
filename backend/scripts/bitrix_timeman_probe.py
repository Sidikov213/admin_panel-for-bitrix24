#!/usr/bin/env python3
"""READ-ONLY Bitrix Timeman / Time Control capability probe (re-runnable).

Distinguishes:
  A) scope exists
  B) Timeman module enabled
  C) Time Control enabled
  D) which fields are actually populated

Never prints webhook/token. Never calls write methods.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

BACKEND = Path(__file__).resolve().parents[1]  # .../backend or /app in Docker
ROOT = BACKEND.parent if (BACKEND.parent / ".env").exists() else BACKEND
sys.path.insert(0, str(BACKEND))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key, val = k.strip(), v.strip().strip('"').strip("'")
        if key.startswith("BITRIX_") or key in {"DEMO_MODE", "DATABASE_URL"}:
            os.environ[key] = val  # override — probe must use latest webhook


for _p in (ROOT / ".env", BACKEND / ".env", Path("/app/.env"), Path("/.env")):
    _load_env_file(_p)

from app.core.config import get_settings
from app.integrations.bitrix.sanitize import sanitize_bitrix_text, sanitize_bitrix_url

READ_METHODS = frozenset(
    {
        "timeman.status",
        "timeman.settings.get",
        "timeman.timecontrol.settings.get",
        "timeman.timecontrol.reports.settings.get",
        "timeman.timecontrol.reports.users.get",
        "timeman.timecontrol.reports.get",
        "timeman.networkrange.get",
        "timeman.networkrange.check",
        "timeman.record.list",
        "timeman.record.field.list",
        "user.get",
        "scope",
        "methods",
        "app.info",
    }
)

WRITE_FORBIDDEN = frozenset(
    {
        "timeman.open",
        "timeman.close",
        "timeman.pause",
        "timeman.settings.set",
        "timeman.timecontrol.settings.set",
        "timeman.timecontrol.report.add",
        "timeman.networkrange.set",
    }
)

WEBHOOK_RE = re.compile(r"(/rest/)[^/\s\"']+/[^/\s\"']+", re.I)
OUT_JSON = Path("/app/docs/manager-control-bitrix-probe-raw.json")
OUT_JSON_FALLBACK = ROOT / "docs" / "manager-control-bitrix-probe-raw.json"


def redact(obj: Any) -> Any:
    if isinstance(obj, str):
        return sanitize_bitrix_text(WEBHOOK_RE.sub(r"\1***/***", obj))
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def mask_name(name: str | None, last: str | None = None) -> str:
    parts = [p for p in [(name or "").strip(), (last or "").strip()] if p]
    if not parts:
        return "Manager"
    return " ".join((p[0] + "***" if len(p) > 1 else p) for p in parts)


class ProbeClient:
    def __init__(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        self._base = (settings.BITRIX_WEBHOOK_URL or "").rstrip("/") + "/"
        self._timeout = 45.0
        self.calls = 0

    @property
    def configured(self) -> bool:
        return bool(self._base and self._base != "/")

    @property
    def sanitized(self) -> str:
        return sanitize_bitrix_url(self._base) if self.configured else ""

    async def call(self, method: str, params: dict[str, Any] | None = None, *, use_api_v3: bool = False) -> dict[str, Any]:
        if method in WRITE_FORBIDDEN:
            return _err(method, "probe_blocked_write", "Write method blocked by probe")
        if method not in READ_METHODS:
            return _err(method, "probe_blocked_unknown", f"Not in probe allow-list: {method}")
        if not self.configured:
            return _err(method, "not_configured", "BITRIX_WEBHOOK_URL missing")

        base_no_slash = self._base.rstrip("/")
        if use_api_v3 and "/rest/" in base_no_slash and "/rest/api/" not in base_no_slash:
            api_base = base_no_slash.replace("/rest/", "/rest/api/", 1) + "/"
        else:
            api_base = self._base
        url = urljoin(api_base, f"{method}.json")

        self.calls += 1
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as http:
                resp = await http.post(url, json=params or {})
            try:
                body = resp.json()
            except Exception:
                body = {"raw": (resp.text or "")[:300]}
            body = redact(body)

            if resp.status_code >= 400 or "error" in body:
                code = str(body.get("error") or f"http_{resp.status_code}")
                desc = str(body.get("error_description") or body.get("error") or "")[:400]
                # REST v3 nested error
                if isinstance(body.get("error"), dict):
                    code = str(body["error"].get("code") or code)
                    desc = str(body["error"].get("message") or desc)[:400]
                return {
                    "ok": False,
                    "method": method,
                    "use_api_v3": use_api_v3,
                    "error_code": code,
                    "error_description": desc,
                    "http_status": resp.status_code,
                    "result_keys": [],
                    "result": None,
                }

            result = body.get("result")
            keys: list[str] = []
            if isinstance(result, dict):
                keys = sorted(result.keys())
            elif isinstance(result, list) and result and isinstance(result[0], dict):
                keys = sorted(result[0].keys())
            return {
                "ok": True,
                "method": method,
                "use_api_v3": use_api_v3,
                "error_code": None,
                "error_description": None,
                "http_status": resp.status_code,
                "result_keys": keys,
                "result": result,
            }
        except Exception as e:
            return _err(method, type(e).__name__, sanitize_bitrix_text(str(e))[:400], use_api_v3=use_api_v3)


def _err(method: str, code: str, desc: str, use_api_v3: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "method": method,
        "use_api_v3": use_api_v3,
        "error_code": code,
        "error_description": desc,
        "http_status": None,
        "result_keys": [],
        "result": None,
    }


def summarize_status(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    return {
        "STATUS": result.get("STATUS"),
        "TIME_START_present": result.get("TIME_START") not in (None, ""),
        "TIME_FINISH_present": result.get("TIME_FINISH") not in (None, ""),
        "DURATION": result.get("DURATION"),
        "TIME_LEAKS": result.get("TIME_LEAKS"),
        "ACTIVE": result.get("ACTIVE"),
        "keys": sorted(result.keys()),
    }


def summarize_tc_settings(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    return {
        "active": result.get("active"),
        "minimum_idle_for_report": result.get("minimum_idle_for_report"),
        "register_offline": result.get("register_offline"),
        "register_idle": result.get("register_idle"),
        "register_desktop": result.get("register_desktop"),
        "keys": sorted(result.keys()),
    }


def summarize_tc_report(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"days_count": 0, "event_types_seen": [], "sources_seen": []}
    days = result.get("days") or []
    if not isinstance(days, list):
        days = []
    event_types: set[str] = set()
    sources: set[str] = set()
    last_ts: str | None = None
    for day in days:
        if not isinstance(day, dict):
            continue
        for rep in day.get("reports") or []:
            if not isinstance(rep, dict):
                continue
            if rep.get("type"):
                event_types.add(str(rep["type"]))
            for sk in ("source_start", "source_finish"):
                if rep.get(sk):
                    sources.add(str(rep[sk]))
            for tk in ("datetime", "date_start", "date_finish", "timestamp"):
                if rep.get(tk):
                    last_ts = str(rep[tk])
    return {
        "days_count": len(days),
        "event_types_seen": sorted(event_types),
        "sources_seen": sorted(sources),
        "has_idle": "IDLE" in event_types,
        "has_offline": "OFFLINE" in event_types,
        "has_desktop": any(t.startswith("DESKTOP_") for t in event_types),
        "has_tm_events": any(t.startswith("TM_") for t in event_types),
        "last_event_ts_sample": last_ts is not None,
    }


def extract_records(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    if isinstance(result, dict):
        for k in ("items", "records", "list", "result"):
            v = result.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # single record
        if "startTime" in result or "TIME_START" in result or "id" in result:
            return [result]
    return []


def record_in_day(rec: dict[str, Any], d: date) -> bool:
    for k in ("startTime", "START_TIME", "TIME_START", "dateStart", "DATE_START"):
        v = rec.get(k)
        if not v:
            continue
        s = str(v)[:10]
        try:
            return date.fromisoformat(s) == d
        except ValueError:
            continue
    return False


async def load_managers_from_db(limit: int = 3) -> list[dict[str, Any]]:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.crm import CrmDeal, CrmManager

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    out: list[dict[str, Any]] = []
    try:
        async with Session() as session:
            q = (
                select(
                    CrmManager.id,
                    CrmManager.bitrix_id,
                    CrmManager.name,
                    CrmManager.last_name,
                    func.count(CrmDeal.id).label("deals"),
                )
                .outerjoin(CrmDeal, CrmDeal.assigned_by_id == CrmManager.id)
                .where(CrmManager.is_active.is_(True))
                .group_by(CrmManager.id)
                .order_by(func.count(CrmDeal.id).desc())
                .limit(limit)
            )
            for r in (await session.execute(q)).all():
                out.append(
                    {
                        "bitrix_user_id": int(r.bitrix_id),
                        "name_masked": mask_name(r.name, r.last_name),
                        "deal_count": int(r.deals or 0),
                    }
                )
    finally:
        await engine.dispose()
    return out


async def crm_activity_capability() -> dict[str, Any]:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.crm import CrmActivity, CrmDeal, CrmManager, DealChangeEvent

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            deals = (await session.execute(select(func.count()).select_from(CrmDeal))).scalar() or 0
            acts = (await session.execute(select(func.count()).select_from(CrmActivity))).scalar() or 0
            mgrs = (await session.execute(select(func.count()).select_from(CrmManager))).scalar() or 0
            evts = (await session.execute(select(func.count()).select_from(DealChangeEvent))).scalar() or 0
        return {
            "availability": "AVAILABLE" if deals > 0 else "NOT AVAILABLE",
            "inventory": {"managers": mgrs, "deals": deals, "activities": acts, "change_events": evts},
            "note": "CRM ACTIVITY ≠ work time",
        }
    finally:
        await engine.dispose()


async def probe_records_for_user(client: ProbeClient, uid: int, start: date, end: date) -> dict[str, Any]:
    """Try classic + a few filter shapes; limited page size."""
    attempts = [
        (
            False,
            {
                "filter": {
                    "userId": uid,
                    "startTime": {"from": f"{start.isoformat()}T00:00:00", "to": f"{end.isoformat()}T23:59:59"},
                },
                "select": ["id", "userId", "startTime", "endTime", "duration", "breakLength", "state"],
                "pagination": {"page": 1, "limit": 30},
            },
        ),
        (
            True,
            {
                "filter": {
                    "userId": uid,
                    "startTime": {"from": f"{start.isoformat()}T00:00:00", "to": f"{end.isoformat()}T23:59:59"},
                },
                "select": ["id", "userId", "startTime", "endTime", "duration", "breakLength", "state"],
                "pagination": {"page": 1, "limit": 30},
            },
        ),
        (False, {"USER_ID": uid, "FROM": start.isoformat(), "TO": end.isoformat()}),
    ]
    last: dict[str, Any] = {}
    for use_v3, params in attempts:
        last = await client.call("timeman.record.list", params, use_api_v3=use_v3)
        await asyncio.sleep(0.3)
        if last.get("ok"):
            recs = extract_records(last.get("result"))
            return {
                "ok": True,
                "error_code": None,
                "error_description": None,
                "use_api_v3": use_v3,
                "record_count": len(recs),
                "records": recs,
                "result_keys": last.get("result_keys"),
            }
    return {
        "ok": False,
        "error_code": last.get("error_code"),
        "error_description": last.get("error_description"),
        "use_api_v3": last.get("use_api_v3"),
        "record_count": 0,
        "records": [],
        "result_keys": [],
    }


async def main() -> int:
    client = ProbeClient()
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=6)

    report: dict[str, Any] = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "webhook": "configured=true" if client.configured else "configured=false",
        "sanitized_base": client.sanitized,
        "read_only": True,
        "write_methods_attempted": False,
        "distinction": {
            "A_scope": {},
            "B_timeman_enabled": {},
            "C_time_control_enabled": {},
            "D_fields": {},
        },
        "method_probes": {},
        "managers_sample": [],
        "history": {},
        "crm_activity": {},
        "gates": {},
    }

    # --- Scope / meta ---
    app_info = await client.call("app.info", {})
    await asyncio.sleep(0.3)
    scope_r = await client.call("scope", {})
    await asyncio.sleep(0.3)
    methods_r = await client.call("methods", {})
    await asyncio.sleep(0.3)

    scope_list: list[str] = []
    license_name = None
    if app_info.get("ok") and isinstance(app_info.get("result"), dict):
        scope_list = list(app_info["result"].get("SCOPE") or [])
        license_name = app_info["result"].get("LICENSE")
    if scope_r.get("ok") and isinstance(scope_r.get("result"), list):
        scope_list = list(scope_r["result"])

    timeman_in_methods = []
    if methods_r.get("ok") and isinstance(methods_r.get("result"), list):
        timeman_in_methods = [m for m in methods_r["result"] if isinstance(m, str) and "timeman" in m.lower()]

    report["license"] = license_name
    report["webhook_scope"] = scope_list
    report["timeman_methods_sample"] = sorted(timeman_in_methods)[:40]
    report["timeman_methods_count"] = len(timeman_in_methods)

    scope_has_timeman = "timeman" in [s.lower() for s in scope_list]
    report["distinction"]["A_scope"] = {
        "scopes": scope_list,
        "has_crm": "crm" in scope_list,
        "has_user_brief": "user_brief" in scope_list or "user" in scope_list,
        "has_timeman": scope_has_timeman,
        "timeman_methods_exposed": len(timeman_in_methods),
    }

    # --- Module settings ---
    for method in (
        "timeman.status",
        "timeman.settings.get",
        "timeman.timecontrol.settings.get",
        "timeman.timecontrol.reports.settings.get",
        "timeman.networkrange.get",
    ):
        r = await client.call(method, {})
        report["method_probes"][method] = {
            "ok": r["ok"],
            "error_code": r.get("error_code"),
            "error_description": r.get("error_description"),
            "http_status": r.get("http_status"),
            "result_keys": r.get("result_keys"),
            "summary": summarize_status(r.get("result"))
            if method == "timeman.status" and r.get("ok")
            else (
                summarize_tc_settings(r.get("result"))
                if method == "timeman.timecontrol.settings.get" and r.get("ok")
                else None
            ),
        }
        await asyncio.sleep(0.35)

    status_self = report["method_probes"]["timeman.status"]
    tc_settings_probe = report["method_probes"]["timeman.timecontrol.settings.get"]
    tc_settings_sum = tc_settings_probe.get("summary") if tc_settings_probe.get("ok") else None

    # B: Timeman enabled
    # - insufficient_scope → scope issue, not module-off
    # - TIMEMAN_TOOL_DISABLED → module off
    # - successful status → enabled
    b_code = status_self.get("error_code") or ""
    b_desc = (status_self.get("error_description") or "").lower()
    if status_self.get("ok"):
        timeman_enabled = "YES"
        b_reason = "timeman.status returned workday payload"
    elif "insufficient_scope" in b_code.lower() or "higher privileges" in b_desc:
        timeman_enabled = "UNKNOWN"
        b_reason = "blocked by scope — cannot infer module enablement"
    elif "TIMEMAN_TOOL_DISABLED" in b_code or "timeman_tool_disabled" in b_desc or "disabled" in b_desc:
        timeman_enabled = "NO"
        b_reason = "portal returned TIMEMAN_TOOL_DISABLED / disabled"
    elif "METHOD_NOT_FOUND" in b_code or "not found" in b_desc:
        timeman_enabled = "UNKNOWN"
        b_reason = "method not found — may be plan/API availability, not clear disable flag"
    else:
        timeman_enabled = "UNKNOWN"
        b_reason = f"error={b_code}"

    report["distinction"]["B_timeman_enabled"] = {
        "value": timeman_enabled,
        "reason": b_reason,
        "status_error": status_self.get("error_code"),
        "status_error_description": status_self.get("error_description"),
    }

    # C: Time Control enabled
    c_code = tc_settings_probe.get("error_code") or ""
    c_desc = (tc_settings_probe.get("error_description") or "").lower()
    if tc_settings_probe.get("ok") and isinstance(tc_settings_sum, dict):
        if tc_settings_sum.get("active") is True:
            time_control_enabled = "YES"
            c_reason = "timecontrol.settings.get active=true"
        elif tc_settings_sum.get("active") is False:
            time_control_enabled = "NO"
            c_reason = "timecontrol.settings.get active=false"
        else:
            time_control_enabled = "UNKNOWN"
            c_reason = "settings payload without clear active flag"
    elif "insufficient_scope" in c_code.lower():
        time_control_enabled = "UNKNOWN"
        c_reason = "blocked by scope"
    elif "TIMEMAN_TOOL_DISABLED" in c_code or "disabled" in c_desc:
        time_control_enabled = "NO"
        c_reason = "tool disabled error"
    else:
        time_control_enabled = "UNKNOWN"
        c_reason = f"error={c_code}"

    report["distinction"]["C_time_control_enabled"] = {
        "value": time_control_enabled,
        "reason": c_reason,
        "settings_summary": tc_settings_sum,
        "error_code": tc_settings_probe.get("error_code"),
        "error_description": tc_settings_probe.get("error_description"),
    }

    # --- Managers sample ---
    try:
        managers = await load_managers_from_db(3)
    except Exception as e:
        managers = []
        report["managers_load_error"] = sanitize_bitrix_text(str(e))[:300]

    status_summaries: list[dict[str, Any]] = []
    if status_self.get("ok") and status_self.get("summary"):
        status_summaries.append(status_self["summary"])

    all_records: list[dict[str, Any]] = []
    tc_summaries: list[dict[str, Any]] = []
    any_status_ok = bool(status_self.get("ok"))

    for m in managers:
        uid = m["bitrix_user_id"]
        entry: dict[str, Any] = {**m, "probes": {}}

        st = await client.call("timeman.status", {"USER_ID": uid})
        await asyncio.sleep(0.35)
        sm = summarize_status(st.get("result")) if st.get("ok") else None
        entry["probes"]["timeman.status"] = {
            "ok": st["ok"],
            "error_code": st.get("error_code"),
            "error_description": st.get("error_description"),
            "summary": sm,
        }
        if sm:
            status_summaries.append(sm)
            any_status_ok = True

        # Time control report — current month
        tc = await client.call(
            "timeman.timecontrol.reports.get",
            {"USER_ID": uid, "YEAR": today.year, "MONTH": today.month},
        )
        await asyncio.sleep(0.35)
        if not tc["ok"]:
            tc = await client.call("timeman.timecontrol.reports.get", {"USER_ID": uid})
            await asyncio.sleep(0.35)
        tcs = summarize_tc_report(tc.get("result")) if tc.get("ok") else None
        entry["probes"]["timeman.timecontrol.reports.get"] = {
            "ok": tc["ok"],
            "error_code": tc.get("error_code"),
            "error_description": tc.get("error_description"),
            "summary": tcs,
        }
        if tcs:
            tc_summaries.append(tcs)

        # History records (7 days window, limited)
        hist = await probe_records_for_user(client, uid, week_ago, today)
        entry["probes"]["timeman.record.list"] = {
            "ok": hist["ok"],
            "error_code": hist.get("error_code"),
            "error_description": hist.get("error_description"),
            "record_count": hist.get("record_count"),
            "use_api_v3": hist.get("use_api_v3"),
        }
        for rec in hist.get("records") or []:
            rec = dict(rec)
            rec["_uid"] = uid
            all_records.append(rec)

        report["managers_sample"].append(entry)

    # --- D: fields ---
    def field_avail(pred) -> str:
        if not status_summaries:
            return "NOT AVAILABLE"
        return "AVAILABLE" if any(pred(s) for s in status_summaries) else "NOT AVAILABLE"

    workday_status = "AVAILABLE" if any_status_ok else "NOT AVAILABLE"
    start_finish = field_avail(lambda s: s.get("TIME_START_present") or s.get("TIME_FINISH_present"))
    duration = field_avail(lambda s: s.get("DURATION") is not None)
    breaks = field_avail(lambda s: s.get("TIME_LEAKS") is not None)

    idle = "NOT AVAILABLE"
    offline = "NOT AVAILABLE"
    desktop = "NOT AVAILABLE"
    last_activity = "NOT AVAILABLE"
    for tcs in tc_summaries:
        if tcs.get("has_idle"):
            idle = "AVAILABLE"
        if tcs.get("has_offline"):
            offline = "AVAILABLE"
        if tcs.get("has_desktop"):
            desktop = "AVAILABLE"
        if tcs.get("last_event_ts_sample") or tcs.get("days_count", 0) > 0:
            if last_activity != "AVAILABLE":
                last_activity = "AVAILABLE" if (tcs.get("has_idle") or tcs.get("has_offline") or tcs.get("has_tm_events")) else last_activity

    # If TC settings say register_* but no events yet
    needs_desktop = "UNKNOWN"
    if isinstance(tc_settings_sum, dict):
        if tc_settings_sum.get("register_desktop") is True:
            needs_desktop = "YES" if desktop != "AVAILABLE" else "NO"
        elif tc_settings_sum.get("register_desktop") is False:
            needs_desktop = "NO"
        if idle == "NOT AVAILABLE" and tc_settings_sum.get("register_idle") is True:
            idle = "NOT AVAILABLE"  # enabled to register but no events in sample
        if offline == "NOT AVAILABLE" and tc_settings_sum.get("register_offline") is True:
            offline = "NOT AVAILABLE"

    # History windows from records + status (status = today current day)
    today_hist = "NOT AVAILABLE"
    yday_hist = "NOT AVAILABLE"
    week_hist = "NOT AVAILABLE"

    if any_status_ok:
        # current workday is "today" presence of status
        today_hist = "AVAILABLE"

    if all_records:
        if any(record_in_day(r, today) for r in all_records):
            today_hist = "AVAILABLE"
        if any(record_in_day(r, yesterday) for r in all_records):
            yday_hist = "AVAILABLE"
        days_hit = set()
        for r in all_records:
            for k in ("startTime", "START_TIME", "TIME_START"):
                v = r.get(k)
                if v:
                    try:
                        days_hit.add(date.fromisoformat(str(v)[:10]))
                    except ValueError:
                        pass
        if len(days_hit) >= 2:
            week_hist = "AVAILABLE"
        elif len(days_hit) == 1:
            week_hist = "LIMITED"
        elif any((m.get("probes", {}).get("timeman.record.list") or {}).get("record_count", 0) > 0 for m in report["managers_sample"]):
            week_hist = "LIMITED"

    # TC days can also count as history for absences
    if any(t.get("days_count", 0) > 0 for t in tc_summaries):
        if week_hist == "NOT AVAILABLE":
            week_hist = "LIMITED"
        # cannot split today/yesterday precisely without day dates — leave as is unless records say

    report["history"] = {
        "today": today_hist,
        "yesterday": yday_hist,
        "last_7_days": week_hist,
        "record_total_in_sample": len(all_records),
        "note": "Limited list only; no bulk import",
    }

    report["distinction"]["D_fields"] = {
        "WORKDAY STATUS": workday_status,
        "START/FINISH": start_finish,
        "DURATION": duration,
        "BREAKS": breaks,
        "LAST ACTIVITY": last_activity,
        "IDLE": idle,
        "OFFLINE": offline,
        "DESKTOP EVENTS": desktop,
        "TODAY HISTORY": today_hist,
        "YESTERDAY HISTORY": yday_hist,
        "7 DAY HISTORY": week_hist,
    }

    try:
        report["crm_activity"] = await crm_activity_capability()
    except Exception as e:
        report["crm_activity"] = {"availability": "NOT AVAILABLE", "error": sanitize_bitrix_text(str(e))[:300]}

    crm = report["crm_activity"].get("availability", "NOT AVAILABLE")

    # Config change needed?
    needs_config = "NO"
    if not scope_has_timeman:
        needs_config = "YES"
    elif timeman_enabled == "NO":
        needs_config = "YES"
    elif time_control_enabled == "NO" and idle == "NOT AVAILABLE" and offline == "NOT AVAILABLE":
        # optional for full product; mark YES only if customer wants idle/desktop
        needs_config = "NO"  # Timeman alone may be enough for start/finish
    if time_control_enabled == "NO":
        # document as optional — gate NEEDS stays NO if basic workday works
        pass

    # Ready
    if scope_has_timeman and workday_status == "AVAILABLE" and start_finish == "AVAILABLE" and crm == "AVAILABLE":
        ready = "YES"
        if time_control_enabled != "YES" or idle == "NOT AVAILABLE":
            ready = "PARTIAL"  # workday yes, presence telemetry partial
    elif crm == "AVAILABLE" and workday_status == "AVAILABLE":
        ready = "PARTIAL"
    elif crm == "AVAILABLE":
        ready = "PARTIAL"
    else:
        ready = "NO"

    # If workday fully available including duration/breaks → YES even without TC
    if (
        scope_has_timeman
        and workday_status == "AVAILABLE"
        and start_finish == "AVAILABLE"
        and duration == "AVAILABLE"
        and crm == "AVAILABLE"
    ):
        ready = "YES" if time_control_enabled == "YES" or idle == "AVAILABLE" else "PARTIAL"

    report["gates"] = {
        "TIMEMAN SCOPE": "YES" if scope_has_timeman else "NO",
        "TIMEMAN ENABLED": timeman_enabled,
        "TIME CONTROL ENABLED": time_control_enabled,
        "WORKDAY STATUS": workday_status,
        "START/FINISH": start_finish,
        "DURATION": duration,
        "BREAKS": breaks,
        "LAST ACTIVITY": last_activity,
        "IDLE": idle,
        "OFFLINE": offline,
        "DESKTOP EVENTS": desktop,
        "TODAY HISTORY": today_hist,
        "YESTERDAY HISTORY": yday_hist,
        "7 DAY HISTORY": week_hist,
        "CRM ACTIVITY METRICS": crm,
        "NEEDS BITRIX CONFIG CHANGE": needs_config,
        "NEEDS DESKTOP APP": needs_desktop,
        "READY TO BUILD MANAGER CONTROL": ready,
    }
    report["call_count"] = client.calls

    # Strip bulky records from manager entries already slim; drop full methods list
    payload = redact(report)
    out_path = OUT_JSON
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        out_path = OUT_JSON_FALLBACK
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload["gates"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["distinction"], ensure_ascii=False, indent=2))
    print(f"raw={out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
