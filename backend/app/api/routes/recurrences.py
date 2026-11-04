"""Recurring task rule endpoints (V2.0)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import get_recurrence_service
from app.schemas import ErrorResponse
from app.schemas_v2 import (
    RecurrenceCreate,
    RecurrenceGenerateResult,
    RecurrenceRead,
    RecurrenceUpdate,
)
from app.services.recurrence_service import RecurrenceService

router = APIRouter(
    prefix="/recurrences",
    tags=["recurrences"],
    responses={
        404: {"model": ErrorResponse, "description": "规则不存在"},
        409: {"model": ErrorResponse, "description": "规则冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
    },
)


@router.get("", response_model=list[RecurrenceRead], summary="列出重复任务规则")
def list_rules(
    service: RecurrenceService = Depends(get_recurrence_service),
) -> list[RecurrenceRead]:
    return service.list()


@router.post(
    "",
    response_model=RecurrenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建重复任务规则并生成近期任务实例",
)
def create_rule(
    payload: RecurrenceCreate,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceRead:
    return service.create(payload)


@router.post(
    "/generate",
    response_model=RecurrenceGenerateResult,
    summary="按需生成到期的重复任务实例（幂等）",
)
def generate(
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceGenerateResult:
    return service.ensure_all()


@router.get("/{rule_id}", response_model=RecurrenceRead, summary="查看一条重复规则")
def get_rule(
    rule_id: UUID,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceRead:
    return service.get(str(rule_id))


@router.patch("/{rule_id}", response_model=RecurrenceRead, summary="修改重复规则")
def update_rule(
    rule_id: UUID,
    payload: RecurrenceUpdate,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceRead:
    return service.update(str(rule_id), payload)


@router.post("/{rule_id}/pause", response_model=RecurrenceRead, summary="暂停重复规则")
def pause_rule(
    rule_id: UUID,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceRead:
    return service.set_paused(str(rule_id), True)


@router.post("/{rule_id}/resume", response_model=RecurrenceRead, summary="恢复重复规则")
def resume_rule(
    rule_id: UUID,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> RecurrenceRead:
    return service.set_paused(str(rule_id), False)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除整个重复系列（保留已完成的历史任务）",
)
def delete_rule(
    rule_id: UUID,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> Response:
    service.delete_series(str(rule_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{rule_id}/instances/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="只删除某一次任务实例，保留重复规则",
)
def delete_instance(
    rule_id: UUID,
    task_id: UUID,
    service: RecurrenceService = Depends(get_recurrence_service),
) -> Response:
    service.delete_instance(str(rule_id), str(task_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
