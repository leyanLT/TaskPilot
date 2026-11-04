"""Calendar range view and time block management (V2.0)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_calendar_service
from app.schemas import ErrorResponse
from app.schemas_v2 import (
    CalendarRangeRead,
    TimeBlockCreate,
    TimeBlockRead,
    TimeBlockUpdate,
)
from app.services.calendar_service import CalendarService

router = APIRouter(
    tags=["calendar"],
    responses={
        404: {"model": ErrorResponse, "description": "资源不存在"},
        409: {"model": ErrorResponse, "description": "时间冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
    },
)


@router.get(
    "/calendar",
    response_model=CalendarRangeRead,
    summary="按日期范围读取日历（任务截止、时间块、重复任务）",
)
def calendar_range(
    start: date,
    end: date,
    project_id: UUID | None = Query(default=None),
    service: CalendarService = Depends(get_calendar_service),
) -> CalendarRangeRead:
    return service.range(start, end, project_id=str(project_id) if project_id else None)


@router.post(
    "/time-blocks",
    response_model=TimeBlockRead,
    status_code=status.HTTP_201_CREATED,
    summary="为任务安排一个时间块",
)
def create_time_block(
    payload: TimeBlockCreate,
    service: CalendarService = Depends(get_calendar_service),
) -> TimeBlockRead:
    return service.create_block(payload)


@router.patch(
    "/time-blocks/{block_id}",
    response_model=TimeBlockRead,
    summary="调整时间块的开始/结束时间",
)
def update_time_block(
    block_id: UUID,
    payload: TimeBlockUpdate,
    service: CalendarService = Depends(get_calendar_service),
) -> TimeBlockRead:
    return service.update_block(str(block_id), payload)


@router.delete(
    "/time-blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="取消一个时间块",
)
def delete_time_block(
    block_id: UUID,
    service: CalendarService = Depends(get_calendar_service),
) -> Response:
    service.delete_block(str(block_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
