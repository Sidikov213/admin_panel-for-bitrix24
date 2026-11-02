from fastapi import APIRouter

from app.analytics.kpi import overdue_activities_query
from app.auth.deps import CurrentUser, DbSession
from app.core.timezone import utc_now
from app.models.crm import CrmActivity

router = APIRouter()


@router.get("")
async def list_overdue(_user: CurrentUser, db: DbSession) -> dict:
    now = utc_now()
    stmt = overdue_activities_query(now, CrmActivity)
    rows = (await db.execute(stmt)).scalars().unique().all()
    seen: set[int] = set()
    items = []
    for a in rows:
        if a.bitrix_id in seen:
            continue
        seen.add(a.bitrix_id)
        items.append(
            {
                "id": a.id,
                "bitrix_id": a.bitrix_id,
                "subject": a.subject,
                "owner_id": a.owner_id,
                "deadline": a.deadline.isoformat() if a.deadline else None,
                "is_overdue": True,
            }
        )
    return {"items": items, "total": len(items)}
