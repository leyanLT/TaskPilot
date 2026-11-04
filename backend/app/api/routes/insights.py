"""Dashboard aggregate, priority insights, and health-adjacent read models."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_dashboard_service, get_priority_service
from app.schemas import (
    DashboardResponse,
    ErrorResponse,
    PrioritySuggestionList,
)
from app.services.dashboard_service import DashboardService
from app.services.priority_service import PriorityService

router = APIRouter(
    tags=["insights"],
    responses={
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="获取今日仪表盘聚合数据",
)
def get_dashboard(
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardResponse:
    return service.build()


@router.get(
    "/insights/priorities",
    response_model=PrioritySuggestionList,
    summary="获取基于真实数据的优先级建议",
)
def priority_suggestions(
    limit: int = Query(default=8, ge=1, le=30),
    project_id: UUID | None = Query(default=None),
    service: PriorityService = Depends(get_priority_service),
) -> PrioritySuggestionList:
    return PrioritySuggestionList(
        suggestions=service.suggestions(limit=limit, project_id=project_id)
    )
