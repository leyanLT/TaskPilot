"""Task risk insights, deterministic replanning, and user preferences (V2.0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import (
    get_insight_service,
    get_preference_service,
    get_replan_service,
)
from app.schemas import ErrorResponse
from app.schemas_v2 import (
    InsightDismissRequest,
    InsightListRead,
    PreferencesRead,
    PreferencesUpdate,
    ReplanApplyRequest,
    ReplanApplyResult,
    ReplanDraftRead,
    ReplanRequest,
)
from app.services.insight_service import InsightService
from app.services.preference_service import PreferenceService
from app.services.replan_service import ReplanService

router = APIRouter(
    tags=["insights", "planning"],
    responses={
        409: {"model": ErrorResponse, "description": "计划已过期或冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
    },
)


@router.get("/insights", response_model=InsightListRead, summary="基于真实数据识别任务风险")
def list_insights(
    service: InsightService = Depends(get_insight_service),
) -> InsightListRead:
    return service.compute()


@router.post(
    "/insights/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="忽略一条风险提示（当天不再出现）",
)
def dismiss_insight(
    payload: InsightDismissRequest,
    service: InsightService = Depends(get_insight_service),
) -> Response:
    service.dismiss(payload.key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/replan/preview",
    response_model=ReplanDraftRead,
    summary="生成确定性的重排方案（不写入数据库）",
)
def preview_replan(
    payload: ReplanRequest,
    service: ReplanService = Depends(get_replan_service),
) -> ReplanDraftRead:
    return service.preview(
        plan_date=payload.plan_date,
        reason=payload.reason,
        available_minutes=payload.available_minutes,
        keep_task_ids=payload.keep_task_ids,
        unavailable_windows=payload.unavailable_windows,
    )


@router.post(
    "/replan/apply",
    response_model=ReplanApplyResult,
    summary="确认并写入重排方案（计划已变化时拒绝）",
)
def apply_replan(
    payload: ReplanApplyRequest,
    service: ReplanService = Depends(get_replan_service),
) -> ReplanApplyResult:
    applied, revision_no = service.apply(
        plan_date=payload.plan_date,
        blocks=payload.blocks,
        plan_token=payload.plan_token,
        reason=payload.reason,
        source="user",
    )
    return ReplanApplyResult(
        plan_date=payload.plan_date,
        applied=applied,
        revision_no=revision_no,
    )


@router.get("/preferences", response_model=PreferencesRead, summary="读取本地偏好设置")
def get_preferences(
    service: PreferenceService = Depends(get_preference_service),
) -> PreferencesRead:
    return service.get()


@router.patch("/preferences", response_model=PreferencesRead, summary="修改偏好设置")
def update_preferences(
    payload: PreferencesUpdate,
    service: PreferenceService = Depends(get_preference_service),
) -> PreferencesRead:
    return service.update(payload)
