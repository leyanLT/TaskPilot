"""Focus session endpoints (V2.0)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_focus_service
from app.schemas import ErrorResponse
from app.schemas_v2 import FocusRead, FocusStart, FocusStatsRead
from app.services.focus_service import FocusService

router = APIRouter(
    prefix="/focus",
    tags=["focus"],
    responses={
        404: {"model": ErrorResponse, "description": "任务或会话不存在"},
        409: {"model": ErrorResponse, "description": "专注状态冲突"},
    },
)


@router.get("/active", response_model=FocusRead | None, summary="读取当前进行中的专注会话")
def active_focus(
    service: FocusService = Depends(get_focus_service),
) -> FocusRead | None:
    return service.active()


@router.post("/start", response_model=FocusRead, summary="开始专注")
def start_focus(
    payload: FocusStart,
    service: FocusService = Depends(get_focus_service),
) -> FocusRead:
    return service.start(payload)


@router.post("/{session_id}/pause", response_model=FocusRead, summary="暂停专注")
def pause_focus(
    session_id: UUID,
    service: FocusService = Depends(get_focus_service),
) -> FocusRead:
    return service.pause(str(session_id))


@router.post("/{session_id}/resume", response_model=FocusRead, summary="恢复专注")
def resume_focus(
    session_id: UUID,
    service: FocusService = Depends(get_focus_service),
) -> FocusRead:
    return service.resume(str(session_id))


@router.post("/{session_id}/stop", response_model=FocusRead, summary="结束专注")
def stop_focus(
    session_id: UUID,
    service: FocusService = Depends(get_focus_service),
) -> FocusRead:
    return service.stop(str(session_id))


@router.get("/stats", response_model=FocusStatsRead, summary="今日与本周专注统计")
def focus_stats(
    reference: date | None = Query(default=None, description="统计参考日期，默认今天"),
    service: FocusService = Depends(get_focus_service),
) -> FocusStatsRead:
    return service.stats(reference=reference)
