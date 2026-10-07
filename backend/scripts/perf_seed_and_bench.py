"""Seed ~5000 deals + activities and bench hot API endpoints."""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DB = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/focus_analytics",
).replace("postgresql+asyncpg://", "postgresql://")
BASE = os.environ.get("AUDIT_API_BASE", "http://127.0.0.1:18000/api/v1")
N_DEALS = int(os.environ.get("PERF_DEALS", "5000"))
N_ACTS = int(os.environ.get("PERF_ACTS", "3000"))


def seed() -> None:
    ph = PasswordHasher()
    eng = create_engine(DB)
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.execute(text("DELETE FROM deal_change_events"))
        s.execute(text("DELETE FROM deal_snapshots"))
        s.execute(text("DELETE FROM crm_activities"))
        s.execute(text("DELETE FROM crm_deals"))
        s.execute(text("DELETE FROM crm_stages"))
        s.execute(text("DELETE FROM crm_pipelines"))
        s.execute(text("DELETE FROM crm_managers"))
        s.execute(text("DELETE FROM sessions"))
        s.execute(text("DELETE FROM login_attempts"))
        s.execute(text("DELETE FROM users WHERE email LIKE 'perf-%' OR email = 'admin@example.com'"))
        s.commit()

        s.execute(
            text(
                "INSERT INTO users (email, password_hash, role, is_active, created_at, updated_at) "
                "VALUES ('admin@example.com', :h, 'admin', true, now(), now()) "
                "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash"
            ),
            {"h": ph.hash("FocusAdmin1!")},
        )
        for i in range(1, 11):
            s.execute(
                text(
                    "INSERT INTO crm_managers (bitrix_id, name, last_name, is_active, created_at, updated_at) "
                    "VALUES (:bid, :n, :ln, true, now(), now())"
                ),
                {"bid": 1000 + i, "n": f"Mgr{i}", "ln": "Perf"},
            )
        s.execute(
            text(
                "INSERT INTO crm_pipelines (bitrix_id, name, sort, created_at, updated_at) VALUES "
                "(1, 'Svai', 10, now(), now()), (39, 'Deferred', 20, now(), now())"
            )
        )
        s.flush()
        pipes = {r[0]: r[1] for r in s.execute(text("SELECT bitrix_id, id FROM crm_pipelines")).all()}
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
        stages = {r[0]: r[1] for r in s.execute(text("SELECT bitrix_id, id FROM crm_stages")).all()}
        mgrs = [r[0] for r in s.execute(text("SELECT id FROM crm_managers")).all()]
        s.commit()

        stage_cycle = ["C1:NEW", "C1:WORK", "C1:WON", "C1:LOST", "C39:NEW"]
        batch = []
        for i in range(N_DEALS):
            st = stage_cycle[i % len(stage_cycle)]
            closed = st in ("C1:WON", "C1:LOST")
            cat = 39 if st.startswith("C39") else 1
            created = now - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23))
            batch.append(
                {
                    "bid": 200000 + i,
                    "title": f"Perf deal {i}",
                    "cat": cat,
                    "stage": stages[st],
                    "mgr": mgrs[i % len(mgrs)],
                    "opp": Decimal(random.randint(10, 5000) * 100),
                    "created": created,
                    "closed": closed,
                    "future": (not closed) and (i % 3 != 0),
                }
            )
            if len(batch) >= 500:
                _insert_deals(s, batch)
                batch.clear()
        if batch:
            _insert_deals(s, batch)

        acts = []
        for i in range(N_ACTS):
            past = i % 5 == 0
            acts.append(
                {
                    "bid": 800000 + i,
                    "owner": 200000 + (i % N_DEALS),
                    "resp": 1001 + (i % 10),
                    "deadline": now - timedelta(hours=2) if past else now + timedelta(days=2),
                    "completed": past and (i % 10 == 0),
                    "now": now,
                }
            )
            if len(acts) >= 500:
                _insert_acts(s, acts)
                acts.clear()
        if acts:
            _insert_acts(s, acts)
        s.commit()
    print(f"SEED_OK deals={N_DEALS} activities={N_ACTS}")


def _insert_deals(s: Session, batch: list[dict]) -> None:
    for row in batch:
        s.execute(
            text(
                "INSERT INTO crm_deals ("
                "bitrix_id, title, category_id, stage_id, assigned_by_id, opportunity, currency_id, "
                "date_create, date_modify, closedate, closed, has_future_activity, open_activities_count, "
                "observed_at, missing_from_bitrix, created_at, updated_at"
                ") VALUES ("
                ":bid, :title, :cat, :stage, :mgr, :opp, 'RUB', :created, :created, "
                ":closedate, :closed, :future, 0, :created, false, now(), now())"
            ),
            {
                **row,
                "closedate": row["created"] if row["closed"] else None,
            },
        )
    s.flush()


def _insert_acts(s: Session, batch: list[dict]) -> None:
    for row in batch:
        s.execute(
            text(
                "INSERT INTO crm_activities ("
                "bitrix_id, type_id, subject, responsible_id, owner_type_id, owner_id, "
                "created, deadline, completed, completed_at, created_at, updated_at"
                ") VALUES ("
                ":bid, 1, 'Perf act', :resp, 2, :owner, :now, :deadline, :completed, "
                "CASE WHEN :completed THEN :now ELSE NULL END, now(), now())"
            ),
            row,
        )
    s.flush()


def bench() -> int:
    with httpx.Client(base_url=BASE, timeout=120.0, trust_env=False) as c:
        r = c.post("/auth/login", json={"email": "admin@example.com", "password": "FocusAdmin1!"})
        if r.status_code != 200:
            print("LOGIN_FAIL", r.status_code, r.text[:200])
            return 1
        endpoints = [
            "/dashboard",
            "/deals?limit=50&offset=0",
            "/managers",
            "/overdue",
            "/stalled?mode=no_future",
        ]
        print("endpoint,ms,status")
        for ep in endpoints:
            # warm + measure
            c.get(ep)
            t0 = time.perf_counter()
            rr = c.get(ep)
            ms = int((time.perf_counter() - t0) * 1000)
            print(f"{ep},{ms},{rr.status_code}")
    return 0


if __name__ == "__main__":
    seed()
    sys.exit(bench())
