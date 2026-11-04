"""Health endpoint used by local checks and Docker."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings
from app.config import Settings
from app.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        agent_configured=settings.agent_enabled,
    )
