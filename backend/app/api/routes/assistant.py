"""Assistant conversation and pending-action confirmation routes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_assistant_service, get_pending_action_service
from app.config import Settings
from app.exceptions import AINotConfiguredError, AppError
from app.schemas import (
    AssistantHistoryResponse,
    AssistantMessageRequest,
    AssistantTurnResponse,
    ConfirmActionRequest,
    ConfirmActionResponse,
    ErrorResponse,
)
from app.services.assistant_service import AssistantService
from app.services.pending_action_service import PendingActionService

logger = logging.getLogger("taskpilot.agent.stream")

router = APIRouter(
    prefix="/assistant",
    tags=["assistant"],
    responses={
        404: {"model": ErrorResponse, "description": "操作不存在"},
        409: {"model": ErrorResponse, "description": "操作状态冲突"},
        410: {"model": ErrorResponse, "description": "操作已过期"},
        502: {"model": ErrorResponse, "description": "AI 上游服务错误"},
        503: {"model": ErrorResponse, "description": "AI 服务未配置或不可用"},
        504: {"model": ErrorResponse, "description": "AI 服务超时"},
    },
)


@router.get(
    "/history",
    response_model=AssistantHistoryResponse,
    summary="获取持久化的助手对话历史",
)
def get_assistant_history(
    limit: int = Query(default=50, ge=1, le=100),
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantHistoryResponse:
    return service.get_history(limit)


@router.post(
    "/messages",
    response_model=AssistantTurnResponse,
    summary="向 AI 助手发送消息（非流式）",
)
def send_assistant_message(
    payload: AssistantMessageRequest,
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantTurnResponse:
    return service.handle_message(payload)


@router.post(
    "/messages/stream",
    summary="向 AI 助手发送消息并流式接收回复",
)
async def stream_assistant_message(
    payload: AssistantMessageRequest,
    request: Request,
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    if not settings.agent_enabled:
        raise AINotConfiguredError()

    async def event_stream() -> AsyncIterator[str]:
        session = request.app.state.session_factory()
        service = AssistantService(session, settings)
        try:
            async for event, data in service.stream_message(payload):
                encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                yield f"event: {event}\ndata: {encoded}\n\n"
        except asyncio.CancelledError:
            raise
        except AppError as exc:
            data = {"error": {"code": exc.code, "message": exc.message}}
            yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Unhandled assistant stream failure")
            data = {
                "error": {
                    "code": "AI_UPSTREAM_ERROR",
                    "message": "AI 服务暂时不可用，请稍后重试。",
                }
            }
            yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/confirm",
    response_model=ConfirmActionResponse,
    summary="确认或取消 AI 操作",
)
def confirm_assistant_action(
    payload: ConfirmActionRequest,
    service: PendingActionService = Depends(get_pending_action_service),
) -> ConfirmActionResponse:
    return service.confirm(
        payload.action_id,
        confirm=payload.confirm,
        payload_overrides=payload.payload_overrides,
    )
