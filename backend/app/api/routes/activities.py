"""Read-only activity log routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_activity_service
from app.schemas import ActivityRead, ErrorResponse
from app.services.activity_service import ActivityService

router = APIRouter(
    prefix="/activities",
    tags=["activities"],
    responses={
        404: {"model": ErrorResponse, "description": "对象不存在"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.get("", response_model=list[ActivityRead], summary="获取真实活动记录")
def list_activities(
    project_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    service: ActivityService = Depends(get_activity_service),
) -> list[ActivityRead]:
    records = service.list_activities(
        project_id=str(project_id) if project_id else None,
        task_id=str(task_id) if task_id else None,
        limit=limit,
    )
    return [ActivityRead.model_validate(record) for record in records]
