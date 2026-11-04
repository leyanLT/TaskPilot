"""Task CRUD, subtask, and project-assignment API routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_task_service
from app.schemas import (
    ErrorResponse,
    SubtaskCreate,
    SubtaskReorder,
    TaskCreate,
    TaskDetail,
    TaskPriority,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from app.services.task_service import TaskService

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={
        404: {"model": ErrorResponse, "description": "任务不存在"},
        409: {"model": ErrorResponse, "description": "任务状态冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建任务",
)
def create_task(
    payload: TaskCreate,
    service: TaskService = Depends(get_task_service),
) -> TaskRead:
    task = service.create_task(payload)
    return TaskRead.from_task(task)


@router.get("", response_model=list[TaskRead], summary="获取任务列表")
def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    sort_by: Literal["created_at", "due_at", "priority"] = Query(default="created_at"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    project_id: UUID | None = Query(default=None),
    priority: TaskPriority | None = Query(default=None),
    include_subtasks: bool = Query(
        default=False,
        description="为 true 时平铺返回子任务；默认只返回顶层任务",
    ),
    limit: int | None = Query(default=None, ge=1, le=200),
    service: TaskService = Depends(get_task_service),
) -> list[TaskRead]:
    return service.list_task_views(
        status=status_filter,
        sort_by=sort_by,
        order=order,
        project_id=project_id,
        priority=priority,
        root_only=not include_subtasks,
        limit=limit,
    )


@router.get("/{task_id}", response_model=TaskDetail, summary="获取任务详情与子任务")
def get_task(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
) -> TaskDetail:
    return service.get_task_detail(task_id)


@router.patch("/{task_id}", response_model=TaskRead, summary="修改任务或状态")
def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    service: TaskService = Depends(get_task_service),
) -> TaskRead:
    task = service.update_task(str(task_id), payload)
    total, completed = service.subtask_counts(task.id)
    return TaskRead.from_task(task, subtask_count=total, completed_subtask_count=completed)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除任务",
)
def delete_task(
    task_id: UUID,
    confirm_subtasks: bool = Query(
        default=False,
        description="父任务包含子任务时必须显式确认，一并删除子任务",
    ),
    service: TaskService = Depends(get_task_service),
) -> Response:
    service.delete_task(str(task_id), confirm_subtasks=confirm_subtasks)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{task_id}/subtasks",
    response_model=list[TaskRead],
    summary="获取任务的子任务",
)
def list_subtasks(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
) -> list[TaskRead]:
    return service.list_subtasks(task_id)


@router.post(
    "/{task_id}/subtasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建子任务",
)
def create_subtask(
    task_id: UUID,
    payload: SubtaskCreate,
    service: TaskService = Depends(get_task_service),
) -> TaskRead:
    subtask = service.create_subtask(task_id, payload)
    return TaskRead.from_task(subtask)


@router.put(
    "/{task_id}/subtasks/order",
    response_model=list[TaskRead],
    summary="调整子任务顺序",
)
def reorder_subtasks(
    task_id: UUID,
    payload: SubtaskReorder,
    service: TaskService = Depends(get_task_service),
) -> list[TaskRead]:
    return service.reorder_subtasks(task_id, payload.subtask_ids)
