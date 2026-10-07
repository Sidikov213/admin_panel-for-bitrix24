"""HTTP audit suite against a running Focus Analytics API."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/v1"
OUT = Path(__file__).resolve().parents[2] / "docs" / "_audit_http_results.json"
results: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": ok, "detail": detail})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")


def main() -> int:
    # trust_env=False: Docker Desktop HTTP_PROXY otherwise hijacks localhost → 503
    with httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=False, trust_env=False) as c:
        # health / ready
        r = c.get("/health")
        record("health", r.status_code == 200 and r.json().get("status") == "ok", str(r.status_code))
        r = c.get("/ready")
        record("ready", r.status_code == 200 and r.json().get("status") == "ready", r.text[:200])

        # unauthorized
        r = c.get("/auth/me")
        record("me_unauthorized", r.status_code == 401, str(r.status_code))
        r = c.get("/dashboard")
        record("dashboard_unauthorized", r.status_code == 401, str(r.status_code))

        # login admin
        r = c.post("/auth/login", json={"email": "audit-admin@example.com", "password": "AuditAdminPass1!"})
        record("admin_login", r.status_code == 200, r.text[:200])
        csrf = c.cookies.get("focus_csrf")
        sess = c.cookies.get("focus_session")
        record("session_cookie", bool(sess), "present" if sess else "missing")
        record("csrf_cookie", bool(csrf), "present" if csrf else "missing")

        r = c.get("/auth/me")
        record("me_ok", r.status_code == 200 and r.json().get("role") == "admin", r.text[:200])

        # openapi
        r = httpx.get(
            BASE.rsplit("/api/v1", 1)[0] + "/openapi.json",
            timeout=30,
            trust_env=False,
        )
        paths = r.json().get("paths", {}) if r.status_code == 200 else {}
        record("openapi", r.status_code == 200 and "/api/v1/dashboard" in paths, f"paths={len(paths)}")
        blob = r.text.lower() if r.status_code == 200 else ""
        record("openapi_no_secrets", "webhook" not in blob or "bitrix_webhook_url" not in blob, "scanned")

        endpoints = [
            ("GET", "/dashboard"),
            ("GET", "/deals?limit=5&offset=0"),
            ("GET", "/managers"),
            ("GET", "/pipelines"),
            ("GET", "/overdue"),
            ("GET", "/stalled?mode=no_future"),
            ("GET", "/stalled?mode=rules"),
            ("GET", "/reports?period_start=2025-01-01&period_end=2025-12-31"),
            ("GET", "/system"),
            ("GET", "/targets"),
        ]
        for method, path in endpoints:
            t0 = time.perf_counter()
            rr = c.request(method, path)
            ms = int((time.perf_counter() - t0) * 1000)
            record(f"{method} {path}", rr.status_code == 200, f"{rr.status_code} {ms}ms")

        # Authenticated checks only if login succeeded
        if any(x["name"] == "admin_login" and x["ok"] for x in results):
            sys_body = c.get("/system").json()
            record(
                "system_bitrix_not_configured",
                sys_body.get("bitrix_configured") is False,
                str(sys_body.get("integrations", {}).get("bitrix")),
            )
            record("system_demo_false", sys_body.get("demo_mode") is False, str(sys_body.get("demo_mode")))

            stalled_rules = c.get("/stalled", params={"mode": "rules"}).json()
            record(
                "stalled_rules_disabled",
                stalled_rules.get("enabled") is False and stalled_rules.get("total") == 0,
                (stalled_rules.get("disclaimer") or "")[:120],
            )

            r = c.post(
                "/targets",
                json={
                    "period_type": "month",
                    "period_start": "2025-03-01",
                    "period_end": "2025-03-31",
                    "amount": "1000",
                    "currency": "RUB",
                },
            )
            record("csrf_blocks_write", r.status_code == 403, str(r.status_code))

            r = c.post(
                "/targets",
                json={
                    "period_type": "month",
                    "period_start": "2025-03-01",
                    "period_end": "2025-03-31",
                    "amount": "1000",
                    "currency": "RUB",
                },
                headers={"X-CSRF-Token": csrf or ""},
            )
            record("admin_create_target", r.status_code == 201, r.text[:200])
            tid = r.json().get("id") if r.status_code == 201 else None

            r = c.post("/auth/logout", headers={"X-CSRF-Token": csrf or ""})
            record("logout", r.status_code == 204, str(r.status_code))
            r = c.get("/auth/me")
            record("me_after_logout", r.status_code == 401, str(r.status_code))

            r = c.post(
                "/auth/login",
                json={"email": "audit-viewer@example.com", "password": "AuditViewerPass1!"},
            )
            record("viewer_login", r.status_code == 200, str(r.status_code))
            csrf_v = c.cookies.get("focus_csrf")
            r = c.get("/dashboard")
            record("viewer_read_dashboard", r.status_code == 200, str(r.status_code))
            r = c.post(
                "/targets",
                json={
                    "period_type": "month",
                    "period_start": "2025-04-01",
                    "period_end": "2025-04-30",
                    "amount": "1",
                    "currency": "RUB",
                },
                headers={"X-CSRF-Token": csrf_v or ""},
            )
            record("viewer_cannot_write_targets", r.status_code == 403, str(r.status_code))

            if tid:
                c.post("/auth/logout", headers={"X-CSRF-Token": csrf_v or ""})
                c.post(
                    "/auth/login",
                    json={"email": "audit-admin@example.com", "password": "AuditAdminPass1!"},
                )
                csrf2 = c.cookies.get("focus_csrf")
                c.delete(f"/targets/{tid}", headers={"X-CSRF-Token": csrf2 or ""})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = sum(1 for x in results if not x["ok"])
    print(f"\nTOTAL {len(results)} FAILED {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
