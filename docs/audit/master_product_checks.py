"""Isolated synthetic audit; never reads project .env or contacts external APIs."""
import os, sys, asyncio, json, time, statistics, logging
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
AUDIT_URL = os.environ['FOCUS_AUDIT_DATABASE_URL']
from sqlalchemy.engine import make_url
u = make_url(AUDIT_URL)
if u.host not in ('127.0.0.1', 'localhost') or not (u.database or '').startswith('focus_audit_'):
    raise SystemExit('Use a NEW local database named focus_audit_*')
os.environ.update(DATABASE_URL=AUDIT_URL, BITRIX_WEBHOOK_URL='', DEMO_MODE='false', SESSION_SECRET='audit-synthetic-only', COOKIE_SECURE='false')
from sqlalchemy import select, func, text, event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from httpx import ASGITransport, AsyncClient
from app.core.config import Settings
Settings.model_config = {**Settings.model_config, 'env_file': None}
from app.main import create_app
from app.db.base import Base
from app.models import *
from app.models.crm import CrmManager, CrmDeal, CrmPipeline, CrmStage, CrmActivity, DealSnapshot
from app.models.auth import User, UserRole
from app.models.sync import SyncRun, SyncType, SyncStatus
from app.models.work_schedules import WorkSchedule, ScheduleAssignment, WorkdayViolation, ManagerControlPolicy
from app.services.schedule_service import resolve_schedule_for_manager
from app.services.violation_evaluator import evaluate_manager_day
from app.services.sync_service import SyncOrchestrator
from app.repositories.sync import SyncRepository, advisory_lock_key
from app.core.security import hash_password
from app.core.config import get_settings
from app.core.timezone import utc_now, app_tz
from app.services.timeman_collector import list_relevant_managers
from app.services.system_service import SystemService
from app.services.sales_rules.engine import _preload_latest_snapshots

OUT = {}
def record(name, **kw):
    OUT[name] = kw
    print(json.dumps({name:kw}, ensure_ascii=True), flush=True)

async def main():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        # New dedicated database created explicitly by the audit; no production schema.
        from sqlalchemy import inspect
        if await c.run_sync(lambda conn: inspect(conn).get_table_names()):
            raise SystemExit('Refusing non-empty database; create a new disposable database')
        await c.run_sync(Base.metadata.create_all)
    record('schema', tables=sorted(Base.metadata.tables), table_count=len(Base.metadata.tables))
    now=utc_now(); today=now.astimezone(app_tz()).date()
    async with factory() as s:
        s.add_all([User(email='audit-admin@example.com', password_hash=hash_password('audit-local-only'), role=UserRole.admin, is_active=True),User(email='audit-viewer@example.com', password_hash=hash_password('audit-local-only'), role=UserRole.viewer, is_active=True)])
        managers=[CrmManager(bitrix_id=70000+i,name=f'Audit {i:02}',last_name='Synthetic',is_active=(i%2==0), raw={'UF_DEPARTMENT':[42]}) for i in range(55)]
        s.add_all(managers); p=CrmPipeline(bitrix_id=1,name='Synthetic pipeline'); s.add(p); await s.flush()
        stages=[CrmStage(bitrix_id=f'C1:{i}',pipeline_id=p.id,name=f'Очень длинное русское название тестового этапа продаж номер {i}',semantics='process') for i in range(12)]
        s.add_all(stages); await s.flush()
        deals=[CrmDeal(bitrix_id=80000+i,title=f'Synthetic deal {i}',category_id=1,stage_id=stages[i%12].id,assigned_by_id=managers[i%55].id,closed=False,opportunity=1000,currency_id='RUB',date_create=now-timedelta(days=1),date_modify=now,has_future_activity=True) for i in range(220)]
        s.add_all(deals); await s.flush()
        s.add_all([CrmActivity(bitrix_id=90000+i,owner_id=deals[i].bitrix_id,owner_type_id=2,responsible_id=managers[i%55].bitrix_id,deadline=now+timedelta(days=1),completed=False,created=now) for i in range(220)])
        sch=WorkSchedule(name='Synthetic 09-18',timezone='Europe/Moscow',weekdays=list(range(1,8)),start_time='09:00',end_time='18:00',required_minutes=480,is_default=False)
        s.add(sch); await s.flush(); s.add(ScheduleAssignment(schedule_id=sch.id,department_key='42'))
        await s.commit()
        direct=await resolve_schedule_for_manager(s,managers[0].id,department_key='42')
        actual=await resolve_schedule_for_manager(s,managers[0].id)
        record('department_assignment', explicit_department_resolves=direct.id if direct else None, production_caller_without_department=actual.id if actual else None)
        first=await list_relevant_managers(s,limit=50); second=await list_relevant_managers(s,limit=50)
        record('collector_starvation', monitored=55, polled_first=len(first), same_ids_next_cycle=[x.id for x in first]==[x.id for x in second], never_polled=sorted(set(m.id for m in managers)-set(m.id for m in first)))
        await s.rollback()
    app=create_app()
    async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url='http://audit') as c:
        resp=await c.post('/api/v1/auth/login',json={'email':'audit-viewer@example.com','password':'audit-local-only'})
        record('viewer_login',http=resp.status_code)
        assert resp.status_code == 200, 'Synthetic login failed; stop diagnostics'
        async with factory() as s:
            before=(await s.execute(select(func.count()).select_from(MonitoredManager))).scalar()
        r=await c.get('/api/v1/manager-control')
        async with factory() as s:
            after=(await s.execute(select(func.count()).select_from(MonitoredManager))).scalar()
            policies=(await s.execute(select(func.count()).select_from(ManagerControlPolicy))).scalar()
        record('viewer_get_mutates',http=r.status_code,roster_before=before,roster_after=after,policies_created=policies)
        blocked=await c.get('/api/v1/manager-control/admin/schedules')
        write=await c.post('/api/v1/manager-control/admin/schedules',json={'name':'X','start_time':'09:00','end_time':'18:00'})
        record('rbac',viewer_admin_get=blocked.status_code,viewer_admin_post=write.status_code)
        for name,url in [('week','/api/v1/manager-control/1/week'),('month','/api/v1/manager-control/1/month'),('team','/api/v1/manager-control/report')]:
            r=await c.get(url); d=r.json()
            record('missing_history_'+name,http=r.status_code,result=d.get('totals',d.get('items',[{}])[0] if 'items' in d else {k:d.get(k) for k in ['marked_days','fact_seconds','fact_display','delta_minutes']}))
        r=await c.get('/api/v1/manager-control/1/month?month=13');record('invalid_month',http=r.status_code,body=r.text[:50])
        # Authentication tested via real session cookies; no auth dependency bypass.
        await c.post('/api/v1/auth/login',json={'email':'audit-admin@example.com','password':'audit-local-only'})
        payload={'name':'Invalid schedule','timezone':'Invalid/Zone','weekdays':[99],'start_time':'99:99','end_time':'nonsense','required_minutes':-10}
        no_csrf=await c.post('/api/v1/manager-control/admin/schedules',json=payload)
        invalid=await c.post('/api/v1/manager-control/admin/schedules',json=payload,headers={'X-CSRF-Token':c.cookies.get('focus_csrf')})
        record('schedule_validation',without_csrf=no_csrf.status_code,invalid_payload_with_csrf=invalid.status_code)
        # No arbitrary network access: synthetic Bitrix reachability patched locally.
        async with factory() as s:
            s.add(SyncRun(sync_type=SyncType.deals,status=SyncStatus.success,started_at=now-timedelta(days=10),finished_at=now-timedelta(days=10)))
            await SyncRepository(s).set_state('last_deals_sync',{'at':(now-timedelta(days=10)).isoformat()});await s.commit()
        with patch.object(SystemService,'_cached_bitrix_ping',new=AsyncMock(return_value=True)),patch.object(get_settings(),'BITRIX_WEBHOOK_URL','https://example.invalid/rest/1/audit-placeholder/'):
            r=await c.get('/api/v1/system');record('dead_worker_freshness',http=r.status_code,data_may_be_stale=r.json().get('data_may_be_stale'))
    async with factory() as s:
        sch=(await s.execute(select(WorkSchedule).where(WorkSchedule.name=='Synthetic 09-18'))).scalar_one();sch.is_default=True
        # No Timeman history whatsoever: should not imply proven employee absence.
        d=await evaluate_manager_day(s,1,today-timedelta(days=1),now=now)
        await s.flush()
        vals=(await s.execute(select(WorkdayViolation.violation_type).where(WorkdayViolation.manager_id==1))).scalars().all()
        record('no_observation_violation',types=list(vals),evaluation=d)
        await s.rollback()
    # Pure repeated snapshot A->B->A, all other payload fields unchanged.
    async with factory() as s:
        o=SyncOrchestrator(s,client=AsyncMock())
        a={'ID':'999001','TITLE':'Synthetic revert','CATEGORY_ID':'1','ASSIGNED_BY_ID':'70000','STAGE_ID':'C1:0','CLOSED':'N','OPPORTUNITY':'100','UF_AUDIT':'A'}
        b={**a,'UF_AUDIT':'B'}
        d=await o._upsert_deal(a);await o._upsert_deal(b);await o._upsert_deal(a)
        snapshots=await _preload_latest_snapshots(s,[d.id])
        record('snapshot_reversion',actual_upstream='A',latest_snapshot_value=snapshots[d.id].get('UF_AUDIT'),snapshots_count=(await s.execute(select(func.count()).select_from(DealSnapshot).where(DealSnapshot.deal_id==d.id))).scalar())
        await s.rollback()
    async with factory() as s:
        d=await s.get(CrmDeal,1)
        act=(await s.execute(select(CrmActivity).where(CrmActivity.owner_id==d.bitrix_id))).scalar_one()
        act.deadline=now-timedelta(minutes=1);await s.commit()
        mock=AsyncMock();mock.crm_activity_list.return_value=[]
        await SyncOrchestrator(s,client=mock).run_activities(full=True)
        await s.refresh(d)
        record('empty_activity_reconcile',existing_activities=(await s.execute(select(func.count()).select_from(CrmActivity).where(CrmActivity.owner_id==d.bitrix_id))).scalar(),has_future_activity=d.has_future_activity)
    # PG session-level advisory lock vs SQLAlchemy session.commit releasing connection.
    lock_engine=create_async_engine(os.environ['DATABASE_URL'],pool_size=2,max_overflow=0)
    lock_factory=async_sessionmaker(lock_engine,expire_on_commit=False)
    async with lock_factory() as s:
        repo=SyncRepository(s); acquired=await repo.try_advisory_lock(SyncType.deals);await s.commit()
        async with lock_engine.connect() as original:
            original_pid=(await original.execute(text('select pg_backend_pid()'))).scalar()
            await repo.advisory_unlock(SyncType.deals)
            unlock_pid=(await s.execute(text('select pg_backend_pid()'))).scalar()
            still_held=(await original.execute(text("select count(*) from pg_locks where locktype='advisory' and pid=pg_backend_pid()"))).scalar()
            record('advisory_unlock_other_connection',acquired=acquired,original_pid=original_pid,unlock_pid=unlock_pid,locks_still_held=still_held)
            await original.execute(text('select pg_advisory_unlock_all()'))
    await lock_engine.dispose()
    # Synthetic API timings: 55 managers, 220 deals, 220 activities; no external calls.
    from app.db.session import engine as app_engine
    query_count=[0]
    @event.listens_for(app_engine.sync_engine,'before_cursor_execute')
    def count(*args): query_count[0]+=1
    async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url='http://audit') as c:
        await c.post('/api/v1/auth/login',json={'email':'audit-viewer@example.com','password':'audit-local-only'})
        for name,url in [('dashboard','/api/v1/dashboard'),('deals','/api/v1/deals'),('manager_list','/api/v1/managers'),('manager_control','/api/v1/manager-control'),('manager_detail','/api/v1/managers/1'),('manager_control_detail','/api/v1/manager-control/1'),('week','/api/v1/manager-control/1/week'),('month','/api/v1/manager-control/1/month'),('team','/api/v1/manager-control/report?period=month'),('pipelines','/api/v1/pipelines?analytics=true'),('reports','/api/v1/reports')]:
            times=[];counts=[];statuses=[]
            for _ in range(3):
                query_count[0]=0;t=time.perf_counter();r=await c.get(url);times.append(round((time.perf_counter()-t)*1000,1));counts.append(query_count[0]);statuses.append(r.status_code)
            record('perf_'+name,ms=times,median_ms=statistics.median(times),sql_counts=counts,statuses=statuses)
    await app_engine.dispose(); await engine.dispose()

if __name__=='__main__':
    try: asyncio.run(main())
    finally: Path(os.environ.get('FOCUS_AUDIT_OUTPUT', 'master-audit-diagnostics.json')).write_text(json.dumps(OUT,ensure_ascii=False,indent=2),encoding='utf-8')
