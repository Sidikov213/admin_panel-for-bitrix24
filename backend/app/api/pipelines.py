from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.deps import CurrentUser, DbSession
from app.models.crm import CrmPipeline

router = APIRouter()


@router.get("")
async def list_pipelines(_user: CurrentUser, db: DbSession) -> list[dict]:
    stmt = select(CrmPipeline).options(selectinload(CrmPipeline.stages)).order_by(CrmPipeline.sort)
    pipes = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": p.id,
            "bitrix_id": p.bitrix_id,
            "name": p.name,
            "sort": p.sort,
            "stages": [
                {"id": s.id, "bitrix_id": s.bitrix_id, "name": s.name, "sort": s.sort, "semantics": s.semantics}
                for s in p.stages
            ],
        }
        for p in pipes
    ]
