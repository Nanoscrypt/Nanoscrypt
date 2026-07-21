from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nanoscrypt.api.dependencies import get_registry
from nanoscrypt.api.routers import (
    agents,
    approval,
    audit,
    health,
    sessions,
    tasks,
    tools,
)
from nanoscrypt.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield
    registry = await get_registry()
    await registry.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Nanoscrypt API",
        description="REST API for the standalone Nanoscrypt tool-synthesis framework",
        version="0.2.0",
        lifespan=lifespan,
    )

    # Enable CORS for frontend integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers under /api/v1 prefix
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(approval.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")

    return app


app = create_app()
