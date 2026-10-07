from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.demo_data import seed_demo_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.DEMO_MODE:
        from app.db.session import async_session_factory

        async with async_session_factory() as session:
            await seed_demo_data(session)
            await session.commit()
    yield


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(title="Focus Analytics", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
