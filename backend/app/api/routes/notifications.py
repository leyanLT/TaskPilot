"""In-app notification routes: derived reminders with persisted read state."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_notification_service
from app.schemas import (
    CountResponse,
    ErrorResponse,
    NotificationList,
    NotificationRead,
    NotificationReadRequest,
)
from app.services.notification_service import NotificationService

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    responses={
        404: {"model": ErrorResponse, "description": "提醒不存在"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.get("", response_model=NotificationList, summary="获取提醒列表")
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationList:
    return service.list(unread_only=unread_only, limit=limit)


@router.get(
    "/unread-count",
    response_model=CountResponse,
    summary="获取未读提醒数量",
)
def unread_count(
    service: NotificationService = Depends(get_notification_service),
) -> CountResponse:
    return CountResponse(count=service.unread_count())


@router.post(
    "/refresh",
    response_model=NotificationList,
    summary="重新同步今日/即将截止/逾期提醒",
)
def refresh_notifications(
    service: NotificationService = Depends(get_notification_service),
) -> NotificationList:
    return service.list()


@router.post(
    "/read-all",
    response_model=CountResponse,
    summary="将全部提醒标记为已读",
)
def mark_all_read(
    service: NotificationService = Depends(get_notification_service),
) -> CountResponse:
    return CountResponse(count=service.mark_all_read())


@router.patch(
    "/{notification_id}",
    response_model=NotificationRead,
    summary="标记提醒已读或未读",
)
def update_notification(
    notification_id: UUID,
    payload: NotificationReadRequest,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationRead:
    return service.mark_read(notification_id, read=payload.read)
