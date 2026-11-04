"""Project CRUD, archive/restore, progress, and recent activity routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_project_service
from app.schemas import (
    ErrorResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectStatus,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    responses={
        404: {"model": ErrorResponse, "description": "项目不存在"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建项目",
)
def create_project(
    payload: ProjectCreate,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    project = service.create_project(payload)
    return service.project_view(project)


@router.get("", response_model=list[ProjectRead], summary="获取项目列表")
def list_projects(
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    include_archived: bool = Query(default=True),
    search: str | None = Query(default=None, max_length=100),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectRead]:
    return service.list_projects(
        status=status_filter,
        include_archived=include_archived,
        search=search,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="获取项目详情、任务与最近活动",
)
def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetail:
    return service.get_project_detail(project_id)


@router.patch("/{project_id}", response_model=ProjectRead, summary="修改项目")
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    project = service.update_project(project_id, payload)
    return service.project_view(project)


@router.post(
    "/{project_id}/archive",
    response_model=ProjectRead,
    summary="归档项目（保留全部历史任务与活动）",
)
def archive_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    project = service.archive_project(project_id)
    return service.project_view(project)


@router.post(
    "/{project_id}/restore",
    response_model=ProjectRead,
    summary="恢复已归档项目",
)
def restore_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
) -> ProjectRead:
    project = service.restore_project(project_id)
    return service.project_view(project)
