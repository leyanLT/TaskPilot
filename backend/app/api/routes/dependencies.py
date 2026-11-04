"""Task dependency endpoints (V2.0)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_dependency_service
from app.schemas import ErrorResponse
from app.schemas_v2 import DependencyCreate, DependencyRead, TaskDependenciesRead
from app.services.dependency_service import DependencyService

router = APIRouter(
    prefix="/dependencies",
    tags=["dependencies"],
    responses={
        404: {"model": ErrorResponse, "description": "任务不存在"},
        409: {"model": ErrorResponse, "description": "依赖规则冲突"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
    },
)


@router.get(
    "/summary",
    response_model=dict[str, list[str]],
    summary="列出任务当前未满足的前置任务标题",
)
def blocked_summary(
    task_ids: list[UUID] | None = Query(default=None),
    service: DependencyService = Depends(get_dependency_service),
) -> dict[str, list[str]]:
    ids = [str(task_id) for task_id in task_ids] if task_ids else None
    return service.blocked_summary(ids)


@router.get(
    "/{task_id}",
    response_model=TaskDependenciesRead,
    summary="查看任务的前置依赖与被依赖关系",
)
def get_dependencies(
    task_id: UUID,
    service: DependencyService = Depends(get_dependency_service),
) -> TaskDependenciesRead:
    return TaskDependenciesRead.model_validate(service.for_task(str(task_id)))


@router.post(
    "/{task_id}",
    response_model=DependencyRead,
    status_code=status.HTTP_201_CREATED,
    summary="为任务添加一个前置任务",
)
def add_dependency(
    task_id: UUID,
    payload: DependencyCreate,
    service: DependencyService = Depends(get_dependency_service),
) -> DependencyRead:
    service.add(str(task_id), str(payload.depends_on_task_id))
    view = service.for_task(str(task_id))
    for item in view["depends_on"]:
        if str(item["depends_on_task_id"]) == str(payload.depends_on_task_id):
            return DependencyRead.model_validate(item)
    raise RuntimeError("dependency view missing after create")


@router.delete(
    "/{task_id}/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除一个前置依赖",
)
def delete_dependency(
    task_id: UUID,
    dependency_id: UUID,
    service: DependencyService = Depends(get_dependency_service),
) -> Response:
    service.remove(str(task_id), str(dependency_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
