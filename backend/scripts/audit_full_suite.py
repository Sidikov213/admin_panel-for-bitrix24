"""Comprehensive Stage-1 HTTP + KPI audit against a running API + Postgres."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

BASE = os.environ.get("AUDIT_API_BASE", "http://127.0.0.1:18000/api/v1")
DB = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
).replace("postgresql+asyncpg://", "postgresql://")

OUT = Path(__file__).resolve().parents[2] / "docs" / "_audit_http_results.json"
results: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": ok, "detail": detail[:500]})
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}: {detail[:200]}")


def sync_url() -> str:
    return DB


def seed_controlled_dataset() -> dict:
    """Insert known CRM rows; return expected KPI numbers."""
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    eng = create_engine(sync_url())
    now = datetime.now(timezone.utc)
    today = date.today()
    with Session(eng) as s:
        s.execute(text("DELETE FROM deal_change_events"))
        s.execute(text("DELETE FROM deal_snapshots"))
        s.execute(text("DELETE FROM crm_activities"))
        s.execute(text("DELETE FROM crm_deals"))
        s.execute(text("DELETE FROM crm_stages"))
        s.execute(text("DELETE FROM crm_pipelines"))
        s.execute(text("DELETE FROM crm_managers"))
        s.execute(text("DELETE FROM sales_targets"))
        s.execute(text("DELETE FROM sessions"))
        s.execute(text("DELETE FROM login_attempts"))
        s.execute(text("DELETE FROM users"))
        s.commit()

        for email, role, pwd in [
            ("audit-admin@example.com", "admin", "AuditAdminPass1!"),
            ("audit-viewer@example.com", "viewer", "AuditViewerPass1!"),
        ]:
            s.execute(
                text(
                    "INSERT INTO users (email, password_hash, role, is_active, created_at, updated_at) "
                    "VALUES (:e, :h, :r, true, now(), now())"
                ),
                {"e": email, "h": ph.hash(pwd), "r": role},
            )

        s.execute(
            text(
                "INSERT INTO crm_managers (bitrix_id, name, last_name, is_active, created_at, updated_at) "
                "VALUES (101, 'Anna', 'Audit', true, now(), now()), "
                "(102, 'Boris', 'Audit', true, now(), now())"
            )
        )
        s.execute(
            text(
                "INSERT INTO crm_pipelines (bitrix_id, name, sort, created_at, updated_at) "
                "VALUES (1, 'Svai', 10, now(), now()), (39, 'Deferred', 20, now(), now())"
            )
        )
        s.flush()
        pipes = {
            r[0]: r[1]
            for r in s.execute(text("SELECT bitrix_id, id FROM crm_pipelines")).all()
        }
        s.execute(
            text(
                "INSERT INTO crm_stages (bitrix_id, pipeline_id, name, sort, semantics, created_at, updated_at) VALUES "
                "('C1:NEW', :p1, 'New', 10, 'process', now(), now()), "
                "('C1:WORK', :p1, 'Work', 20, 'process', now(), now()), "
                "('C1:WON', :p1, 'Won', 30, 'success', now(), now()), "
                "('C1:LOST', :p1, 'Lost', 40, 'failure', now(), now()), "
                "('C39:NEW', :p39, 'New39', 10, 'process', now(), now())"
            ),
            {"p1": pipes[1], "p39": pipes[39]},
        )
        stages = {
            r[0]: r[1]
            for r in s.execute(text("SELECT bitrix_id, id FROM crm_stages")).all()
        }
        mgrs = {
            r[0]: r[1]
            for r in s.execute(text("SELECT bitrix_id, id FROM crm_managers")).all()
        }

        # 10 deals: 6 active, 2 won, 2 lost; 2 new in period (date_create=now)
        # active sum = 100+200+300+400+50+60 = 1110
        # won sum = 1000+2000 = 3000
        # 3 without future activity among active: deals 1,2,3 (has_future false)
        deals = [
            # bitrix, title, cat, stage, mgr, opp, closed, create, has_future
            (1001, "A1", 1, "C1:NEW", 101, 100, False, now, False),
            (1002, "A2", 1, "C1:WORK", 101, 200, False, now - timedelta(days=10), False),
            (1003, "A3", 1, "C1:WORK", 102, 300, False, now - timedelta(days=5), False),
            (1004, "A4", 1, "C1:WORK", 102, 400, False, now - timedelta(days=3), True),
            (1005, "A5", 39, "C39:NEW", 101, 50, False, now - timedelta(days=2), True),
            (1006, "A6", 39, "C39:NEW", 102, 60, False, now - timedelta(days=1), True),
            (1007, "W1", 1, "C1:WON", 101, 1000, True, now - timedelta(days=20), False),
            (1008, "W2", 1, "C1:WON", 102, 2000, True, now - timedelta(days=15), False),
            (1009, "L1", 1, "C1:LOST", 101, 10, True, now - timedelta(days=12), False),
            (1010, "L2", 1, "C1:LOST", 102, 20, True, now - timedelta(days=8), False),
        ]
        for bid, title, cat, st, mgr, opp, closed, created, future in deals:
            s.execute(
                text(
                    "INSERT INTO crm_deals ("
                    "bitrix_id, title, category_id, stage_id, assigned_by_id, opportunity, currency_id, "
                    "date_create, date_modify, closedate, closed, has_future_activity, open_activities_count, "
                    "observed_at, created_at, updated_at"
                    ") VALUES ("
                    ":bid, :title, :cat, :stage, :mgr, :opp, 'RUB', :created, :created, "
                    ":closedate, :closed, :future, :open_cnt, :created, now(), now())"
                ),
                {
                    "bid": bid,
                    "title": title,
                    "cat": cat,
                    "stage": stages[st],
                    "mgr": mgrs[mgr],
                    "opp": opp,
                    "created": created,
                    "closedate": created if closed else None,
                    "closed": closed,
                    "future": future,
                    "open_cnt": 1 if not closed else 0,
                },
            )

        # Activities: 2 unique overdue open, 1 future, 1 completed past (not overdue)
        # Duplicate bitrix_id must not exist — uniqueness enforced
        s.execute(
            text(
                "INSERT INTO crm_activities ("
                "bitrix_id, type_id, subject, responsible_id, owner_type_id, owner_id, "
                "created, deadline, completed, completed_at, created_at, updated_at"
                ") VALUES "
                "(5001, 1, 'Overdue A', 101, 2, 1001, :now, :past, false, null, now(), now()), "
                "(5002, 1, 'Overdue B', 102, 2, 1002, :now, :past, false, null, now(), now()), "
                "(5003, 1, 'Future', 101, 2, 1004, :now, :future, false, null, now(), now()), "
                "(5004, 1, 'Done past', 101, 2, 1003, :now, :past, true, :now, now(), now())"
            ),
            {
                "now": now,
                "past": now - timedelta(hours=5),
                "future": now + timedelta(days=2),
            },
        )
        s.commit()

    expected = {
        "new_deals_count": 2,  # A1 + maybe only those with create in last 30d — actually many are in 30d
        # Recalculate: period last 30 days includes almost all creates except maybe none
        # A1 now, A2 -10d, A3 -5d, A4 -3d, A5 -2d, A6 -1d, W1 -20d, W2 -15d, L1 -12d, L2 -8d
        # All 10 within 30 days if we use 30-day window
        "active_deals_count": 6,
        "won_count": 2,
        "lost_count": 2,
        "sum_active_opportunity": 1110.0,
        "sum_won_opportunity": 3000.0,
        "overdue_activities_unique": 2,
        "deals_without_future_activity_count": 3,
    }
    # new in 30d = all 10
    expected["new_deals_count_30d"] = 10
    return expected


def main() -> int:
    expected = seed_controlled_dataset()
    # trust_env=False: Windows/system proxies can intercept 127.0.0.1 and return 503
    with httpx.Client(base_url=BASE, timeout=60.0, trust_env=False) as c:
        r = c.get("/health")
        record("health", r.status_code == 200, str(r.status_code))
        r = c.get("/ready")
        record("ready", r.status_code == 200 and r.json().get("database") == "ok", r.text)

        r = c.get("/auth/me")
        record("me_unauthorized", r.status_code == 401, str(r.status_code))

        r = c.post(
            "/auth/login",
            json={"email": "audit-admin@example.com", "password": "wrong-password-xx"},
        )
        record("bad_password", r.status_code == 401, str(r.status_code))
        r = c.post("/auth/login", json={"email": "audit-admin@example.com", "password": "short"})
        record("short_password_validation", r.status_code == 422, str(r.status_code))

        r = c.post(
            "/auth/login",
            json={"email": "audit-admin@example.com", "password": "AuditAdminPass1!"},
        )
        record("admin_login", r.status_code == 200, r.text)
        cookies = c.cookies
        record("session_cookie", "focus_session" in cookies, "present" if "focus_session" in cookies else "missing")
        record("csrf_cookie", "focus_csrf" in cookies, "present" if "focus_csrf" in cookies else "missing")

        # Cookie flags via Set-Cookie — inspect this response, then refresh CSRF from jar
        sc = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else [r.headers.get("set-cookie", "")]
        joined = " ".join(sc) if isinstance(sc, list) else str(sc)
        record("cookie_httponly", "HttpOnly" in joined or "httponly" in joined.lower(), joined[:200])
        record("cookie_samesite", "samesite=lax" in joined.lower(), joined[:200])
        csrf = c.cookies.get("focus_csrf")

        r = c.get("/auth/me")
        record("me_ok", r.status_code == 200 and r.json().get("role") == "admin", r.text)

        # OpenAPI lives at app root, not under /api/v1
        r = c.get("http://127.0.0.1:18000/openapi.json")
        paths = list((r.json().get("paths") or {}).keys()) if r.status_code == 200 else []
        record("openapi", r.status_code == 200 and len(paths) >= 10, f"paths={len(paths)}")
        blob = r.text.lower()
        record(
            "openapi_no_secrets",
            "bitrix_webhook_url" not in blob and "session_secret" not in blob,
            "scanned",
        )

        endpoints = [
            "/dashboard",
            "/deals?limit=5&offset=0",
            "/managers",
            "/pipelines",
            "/overdue",
            "/stalled?mode=no_future",
            "/stalled?mode=rules",
            f"/reports?period_start={(date.today()-timedelta(days=29)).isoformat()}&period_end={date.today().isoformat()}",
            "/system",
            "/targets",
        ]
        for ep in endpoints:
            t0 = datetime.now(timezone.utc)
            r = c.get(ep)
            ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            record(f"GET {ep.split('?')[0]}", r.status_code == 200, f"{r.status_code} {ms}ms")

        # KPI check
        r = c.get("/dashboard")
        if r.status_code != 200:
            record("kpi_dashboard_http", False, f"{r.status_code} {r.text[:200]}")
            k = {}
        else:
            k = r.json().get("kpis", {})
        kpi_snapshot = {
            kk: k.get(kk)
            for kk in [
                "active_deals_count",
                "won_count",
                "lost_count",
                "sum_active_opportunity",
                "sum_won_opportunity",
                "overdue_activities_unique",
                "deals_without_future_activity_count",
            ]
        }
        checks = [
            ("kpi_active", k.get("active_deals_count") == expected["active_deals_count"]),
            ("kpi_won", k.get("won_count") == expected["won_count"]),
            ("kpi_lost", k.get("lost_count") == expected["lost_count"]),
            ("kpi_sum_active", float(k.get("sum_active_opportunity") or 0) == expected["sum_active_opportunity"]),
            ("kpi_sum_won", float(k.get("sum_won_opportunity") or 0) == expected["sum_won_opportunity"]),
            ("kpi_overdue", k.get("overdue_activities_unique") == expected["overdue_activities_unique"]),
            (
                "kpi_no_future",
                k.get("deals_without_future_activity_count") == expected["deals_without_future_activity_count"],
            ),
        ]
        for name, ok in checks:
            record(name, ok, json.dumps(kpi_snapshot))

        r = c.get("/stalled", params={"mode": "rules"})
        record("stalled_rules_disabled", r.status_code == 200 and r.json().get("enabled") is False, r.text[:200])

        r = c.get("/stalled", params={"mode": "no_future"})
        record(
            "stalled_no_future_count",
            r.status_code == 200 and r.json().get("total") == 3,
            r.text[:200],
        )

        r = c.get("/system")
        sysb = r.json()
        record(
            "system_bitrix_not_configured",
            sysb.get("bitrix_configured") is False,
            json.dumps({"configured": sysb.get("bitrix_configured"), "demo": sysb.get("demo_mode")}),
        )

        # Deals pagination
        r1 = c.get("/deals", params={"limit": 3, "offset": 0, "sort_by": "title", "sort_dir": "asc"})
        r2 = c.get("/deals", params={"limit": 3, "offset": 3, "sort_by": "title", "sort_dir": "asc"})
        ids1 = [x["id"] for x in r1.json().get("items", [])]
        ids2 = [x["id"] for x in r2.json().get("items", [])]
        record(
            "deals_pagination",
            r1.json().get("total") == 10 and len(ids1) == 3 and len(ids2) == 3 and not set(ids1) & set(ids2),
            f"total={r1.json().get('total')} p1={ids1} p2={ids2}",
        )

        r = c.get("/deals/999999")
        record("deal_404", r.status_code == 404, str(r.status_code))

        # CSRF / RBAC targets
        today_start = date.today().replace(day=1).isoformat()
        r = c.post(
            "/targets",
            json={
                "manager_id": None,
                "period_type": "month",
                "period_start": today_start,
                "period_end": date.today().isoformat(),
                "amount": "100000",
                "currency": "RUB",
            },
        )
        record("targets_csrf_required", r.status_code == 403, str(r.status_code))

        r = c.post(
            "/targets",
            headers={"X-CSRF-Token": csrf or ""},
            json={
                "manager_id": None,
                "period_type": "month",
                "period_start": today_start,
                "period_end": date.today().isoformat(),
                "amount": "100000",
                "currency": "RUB",
            },
        )
        record("targets_admin_create", r.status_code == 201, r.text[:200])
        tid = r.json().get("id") if r.status_code == 201 else None

        c.post("/auth/logout", headers={"X-CSRF-Token": csrf or ""})
        r = c.get("/auth/me")
        record("logout_invalidates", r.status_code == 401, str(r.status_code))

        r = c.post(
            "/auth/login",
            json={"email": "audit-viewer@example.com", "password": "AuditViewerPass1!"},
        )
        csrf_v = c.cookies.get("focus_csrf")
        record("viewer_login", r.status_code == 200, r.text[:100])
        r = c.get("/dashboard")
        record("viewer_read_dashboard", r.status_code == 200, str(r.status_code))
        r = c.post(
            "/targets",
            headers={"X-CSRF-Token": csrf_v or ""},
            json={
                "manager_id": None,
                "period_type": "week",
                "period_start": date.today().isoformat(),
                "period_end": date.today().isoformat(),
                "amount": "1",
                "currency": "RUB",
            },
        )
        record("viewer_cannot_write_targets", r.status_code == 403, str(r.status_code))

        # bruteforce
        c.post("/auth/logout", headers={"X-CSRF-Token": csrf_v or ""})
        locked = False
        for i in range(6):
            rr = c.post(
                "/auth/login",
                json={"email": "audit-admin@example.com", "password": "wrong-pass-xx"},
            )
            if rr.status_code == 429:
                locked = True
                break
        record("bruteforce_lock", locked, f"last={rr.status_code}")

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [x for x in results if not x["ok"]]
    print(f"\nTOTAL={len(results)} FAIL={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
