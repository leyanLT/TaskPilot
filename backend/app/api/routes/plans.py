"""Daily plan read/write routes and deterministic plan suggestions."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_planning_service
from app.schemas import (
    ErrorResponse,
    PlanRead,
    PlanSuggestionItem,
    PlanSuggestionResponse,
    PlanUpsert,
)
from app.services.planning_service import PlanningService

router = APIRouter(
    prefix="/plans",
    tags=["plans"],
    responses={
        404: {"model": ErrorResponse, "description": "计划不存在"},
        409: {"model": ErrorResponse, "description": "计划时间冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.get(
    "/{plan_date}",
    response_model=PlanRead,
    summary="获取某一天的今日计划",
)
def get_plan(
    plan_date: date,
    service: PlanningService = Depends(get_planning_service),
) -> PlanRead:
    return service.get_plan(plan_date)


@router.put(
    "/{plan_date}",
    response_model=PlanRead,
    summary="保存或替换某一天的计划",
)
def save_plan(
    plan_date: date,
    payload: PlanUpsert,
    service: PlanningService = Depends(get_planning_service),
) -> PlanRead:
    return service.save_plan(plan_date, payload)


@router.delete(
    "/{plan_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="取消某一天的计划",
)
def delete_plan(
    plan_date: date,
    service: PlanningService = Depends(get_planning_service),
) -> Response:
    service.delete_plan(plan_date)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{plan_date}/suggestion",
    response_model=PlanSuggestionResponse,
    summary="根据真实任务与可用时间生成确定性时间块建议",
)
def suggest_plan(
    plan_date: date,
    available_minutes: int = Query(default=300, ge=5, le=1440),
    service: PlanningService = Depends(get_planning_service),
) -> PlanSuggestionResponse:
    blocks = service.suggest_blocks(plan_date, available_minutes)
    return PlanSuggestionResponse(
        plan_date=plan_date,
        available_minutes=available_minutes,
        blocks=[PlanSuggestionItem.model_validate(block) for block in blocks],
    )
