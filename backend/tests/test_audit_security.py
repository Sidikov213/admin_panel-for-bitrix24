"""Regression tests from Stage 1 audit: auth, CSRF, RBAC, lockout, ready."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.kpi import compute_period_kpis
from app.auth.password import hash_password, verify_password
from app.core.timezone import utc_now
from app.models.auth import LoginAttempt, User, UserRole
from app.models.crm import CrmActivity, CrmDeal, CrmPipeline, CrmStage
from app.models.sync import SyncState, SyncStatus, SyncType
from app.repositories.sync import SyncRepository
from app.services.sync_service import SyncOrchestrator


@pytest.mark.asyncio
async def test_password_is_argon2(db_session: AsyncSession) -> None:
    h = hash_password("SecurePass123!")
    assert h.startswith("$argon2")
    assert verify_password("SecurePass123!", h)
    assert not verify_password("wrong", h)


@pytest.mark.asyncio
async def test_me_unauthorized(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_password_same_message(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="a@ex.com",
            password_hash=hash_password("right-password"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await db_session.commit()
    bad = await client.post("/api/v1/auth/login", json={"email": "a@ex.com", "password": "wrong-password"})
    missing = await client.post(
        "/api/v1/auth/login", json={"email": "nouser@ex.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    assert missing.status_code == 401
    assert bad.json()["detail"] == missing.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_login_sets_httponly_session_cookie(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="cookie@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"email": "cookie@ex.com", "password": "password123"})
    assert r.status_code == 200
    assert "password" not in r.text.lower() or "password_hash" not in r.text
    assert "password_hash" not in r.json()
    assert client.cookies.get("focus_session")
    assert client.cookies.get("focus_csrf")
    # Set-Cookie flags (httpx exposes cookies but headers carry attributes)
    set_cookie = ";".join(r.headers.get_list("set-cookie"))
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()


@pytest.mark.asyncio
async def test_logout_invalidates_session(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="out@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "out@ex.com", "password": "password123"})
    csrf = client.cookies.get("focus_csrf")
    r = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf or ""})
    assert r.status_code == 204
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_csrf_required_for_targets(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="admin@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "admin@ex.com", "password": "password123"})
    body = {
        "period_type": "month",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "amount": "1000",
        "currency": "RUB",
    }
    no_csrf = await client.post("/api/v1/targets", json=body)
    assert no_csrf.status_code == 403
    csrf = client.cookies.get("focus_csrf")
    ok = await client.post("/api/v1/targets", json=body, headers={"X-CSRF-Token": csrf or ""})
    assert ok.status_code == 201


@pytest.mark.asyncio
async def test_bruteforce_lockout(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="lock@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    await db_session.commit()
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"email": "lock@ex.com", "password": "bad-password"})
        assert r.status_code == 401
    locked = await client.post("/api/v1/auth/login", json={"email": "lock@ex.com", "password": "password123"})
    assert locked.status_code == 429
    attempts = (
        await db_session.execute(select(LoginAttempt).where(LoginAttempt.email == "lock@ex.com"))
    ).scalars().all()
    assert len(attempts) >= 5


@pytest.mark.asyncio
async def test_admin_can_crud_targets(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="adm2@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "adm2@ex.com", "password": "password123"})
    csrf = client.cookies.get("focus_csrf")
    created = await client.post(
        "/api/v1/targets",
        json={
            "period_type": "month",
            "period_start": "2025-02-01",
            "period_end": "2025-02-28",
            "amount": "5000",
            "currency": "RUB",
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert created.status_code == 201
    tid = created.json()["id"]
    patched = await client.patch(
        f"/api/v1/targets/{tid}",
        json={"amount": "6000"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert patched.status_code == 200
    assert float(patched.json()["amount"]) == 6000
    deleted = await client.delete(f"/api/v1/targets/{tid}", headers={"X-CSRF-Token": csrf or ""})
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_controlled_kpi_dataset(db_session: AsyncSession) -> None:
    """10 deals: 6 active, 2 won, 2 lost; expected overdue=2 unique; no_future=3."""
    now = utc_now()
    pipe = CrmPipeline(bitrix_id=1, name="Сваи", sort=0)
    pipe2 = CrmPipeline(bitrix_id=39, name="Отложенный", sort=1)
    db_session.add_all([pipe, pipe2])
    await db_session.flush()
    s_proc = CrmStage(bitrix_id="P:NEW", pipeline_id=pipe.id, name="New", sort=0, semantics="process")
    s_won = CrmStage(bitrix_id="P:WON", pipeline_id=pipe.id, name="Won", sort=1, semantics="success")
    s_lost = CrmStage(bitrix_id="P:LOST", pipeline_id=pipe.id, name="Lost", sort=2, semantics="failure")
    s_proc2 = CrmStage(bitrix_id="D:NEW", pipeline_id=pipe2.id, name="New", sort=0, semantics="process")
    db_session.add_all([s_proc, s_won, s_lost, s_proc2])
    await db_session.flush()

    # 6 active (3 with no future), 2 won, 2 lost
    for i in range(6):
        db_session.add(
            CrmDeal(
                bitrix_id=1000 + i,
                title=f"Active {i}",
                closed=False,
                stage_id=s_proc.id if i < 4 else s_proc2.id,
                category_id=1 if i < 4 else 39,
                date_create=now if i < 2 else now - timedelta(days=10),
                opportunity=Decimal("100"),
                has_future_activity=i >= 3,  # 0,1,2 → no future
            )
        )
    for i in range(2):
        db_session.add(
            CrmDeal(
                bitrix_id=2000 + i,
                title=f"Won {i}",
                closed=True,
                stage_id=s_won.id,
                category_id=1,
                date_create=now - timedelta(days=40),
                closedate=now,
                date_modify=now,
                opportunity=Decimal("500"),
            )
        )
    for i in range(2):
        db_session.add(
            CrmDeal(
                bitrix_id=3000 + i,
                title=f"Lost {i}",
                closed=True,
                stage_id=s_lost.id,
                category_id=1,
                date_create=now - timedelta(days=40),
                closedate=now,
                date_modify=now,
                opportunity=Decimal("50"),
            )
        )
    # 3 overdue activities for same bitrix deal owner — unique count by bitrix_id of activity
    db_session.add(
        CrmActivity(
            bitrix_id=9001,
            subject="A1",
            owner_type_id=2,
            owner_id=1000,
            deadline=now - timedelta(hours=2),
            completed=False,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9002,
            subject="A2",
            owner_type_id=2,
            owner_id=1000,
            deadline=now - timedelta(hours=1),
            completed=False,
        )
    )
    db_session.add(
        CrmActivity(
            bitrix_id=9003,
            subject="Done",
            owner_type_id=2,
            owner_id=1001,
            deadline=now - timedelta(hours=1),
            completed=True,
        )
    )
    await db_session.commit()

    today = date.today()
    kpis = await compute_period_kpis(db_session, today - timedelta(days=7), today)
    assert kpis["active_deals_count"] == 6
    assert kpis["won_count"] == 2
    assert kpis["lost_count"] == 2
    assert kpis["new_deals_count"] == 2
    assert kpis["sum_active_opportunity"] == 600.0
    assert kpis["sum_won_opportunity"] == 1000.0
    assert kpis["overdue_activities_unique"] == 2  # not 3, completed excluded; unique by activity
    assert kpis["deals_without_future_activity_count"] == 3


@pytest.mark.asyncio
async def test_stalled_rules_disabled_by_default(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="v@ex.com",
            password_hash=hash_password("password123"),
            role=UserRole.viewer,
            is_active=True,
        )
    )
    db_session.add(
        CrmDeal(
            bitrix_id=55,
            title="No future",
            closed=False,
            has_future_activity=False,
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "v@ex.com", "password": "password123"})
    rules = await client.get("/api/v1/stalled", params={"mode": "rules"})
    assert rules.status_code == 200
    body = rules.json()
    assert body["enabled"] is False
    assert body["total"] == 0
    no_future = await client.get("/api/v1/stalled", params={"mode": "no_future"})
    assert no_future.status_code == 200
    assert no_future.json()["total"] == 1


@pytest.mark.asyncio
async def test_failed_sync_does_not_advance_cursor(db_session: AsyncSession) -> None:
    class FailingClient:
        async def crm_deal_list(self, **kwargs):
            raise Exception("boom mid-sync")  # noqa: TRY002 — simulated Bitrix failure path via generic

    # Use BitrixClientError path
    from app.integrations.bitrix.client import BitrixClientError

    class FailBitrix:
        async def crm_deal_list(self, **kwargs):
            raise BitrixClientError("upstream down")

    orch = SyncOrchestrator(db_session, client=FailBitrix())  # type: ignore[arg-type]
    # Bypass advisory lock for sqlite
    async def always_lock(_t):
        return True

    async def noop_unlock(_t):
        return None

    orch._sync_repo.try_advisory_lock = always_lock  # type: ignore[method-assign]
    orch._sync_repo.advisory_unlock = noop_unlock  # type: ignore[method-assign]
    await orch._sync_repo.set_state("last_deals_sync", {"at": "2025-01-01T00:00:00+00:00"})
    await db_session.commit()

    await orch.run_deals(full=False)
    state = await orch._sync_repo.get_state("last_deals_sync")
    assert state is not None
    assert state["at"] == "2025-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_snapshot_not_duplicated_without_change(db_session: AsyncSession) -> None:
    pipe = CrmPipeline(bitrix_id=1, name="P", sort=0)
    db_session.add(pipe)
    await db_session.flush()
    stage = CrmStage(bitrix_id="C1:NEW", pipeline_id=pipe.id, name="New", sort=0)
    db_session.add(stage)
    await db_session.flush()
    raw = {
        "ID": "777",
        "TITLE": "Same",
        "CATEGORY_ID": "1",
        "STAGE_ID": "C1:NEW",
        "CLOSED": "N",
        "OPPORTUNITY": "10",
    }
    orch = SyncOrchestrator(db_session, client=object())  # type: ignore[arg-type]
    await orch._upsert_deal(raw)
    await orch._upsert_deal(raw)
    await db_session.commit()
    from app.models.crm import DealSnapshot

    deal = (await db_session.execute(select(CrmDeal).where(CrmDeal.bitrix_id == 777))).scalar_one()
    snaps = (
        await db_session.execute(select(DealSnapshot).where(DealSnapshot.deal_id == deal.id))
    ).scalars().all()
    assert len(snaps) == 1


@pytest.mark.asyncio
async def test_ready_ok(client: AsyncClient) -> None:
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
