"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import (
    activities,
    assistant,
    calendar,
    dependencies,
    focus,
    health,
    insights,
    notifications,
    plans,
    projects,
    recurrences,
    reports,
    reports_v2,
    risks,
    tasks,
)
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.exceptions import register_exception_handlers
from app.migrations import prepare_database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        prepare_database(settings, engine)
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "TaskPilot V2.0 —— 单用户 AI 工作管理 API：任务与依赖、重复任务、"
            "专注记录、日历时间块、动态规划、风险识别与增强报告。"
            "AI 写操作必须先创建服务端待确认操作，并由用户明确确认。"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.include_router(activities.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(reports_v2.router, prefix="/api")
    app.include_router(insights.router, prefix="/api")
    app.include_router(assistant.router, prefix="/api")
    # V2.0
    app.include_router(dependencies.router, prefix="/api")
    app.include_router(recurrences.router, prefix="/api")
    app.include_router(focus.router, prefix="/api")
    app.include_router(calendar.router, prefix="/api")
    app.include_router(risks.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
        }

    return app


app = create_app()
