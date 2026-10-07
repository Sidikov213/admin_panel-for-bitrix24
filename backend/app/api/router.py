from fastapi import APIRouter

from app.api import (
    analytics,
    auth,
    deals,
    health,
    managers,
    overdue,
    pipelines,
    reports,
    stalled,
    system,
    targets,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(analytics.router, tags=["analytics"])
api_router.include_router(deals.router, prefix="/deals", tags=["deals"])
api_router.include_router(managers.router, prefix="/managers", tags=["managers"])
api_router.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
api_router.include_router(overdue.router, prefix="/overdue", tags=["overdue"])
api_router.include_router(stalled.router, prefix="/stalled", tags=["stalled"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(targets.router, prefix="/targets", tags=["targets"])
