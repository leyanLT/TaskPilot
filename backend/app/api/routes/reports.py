"""Report generation, persistence, and Markdown export routes."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse

from app.api.dependencies import get_app_settings, get_report_service
from app.config import Settings
from app.schemas import (
    ErrorResponse,
    ReportCreate,
    ReportDraft,
    ReportGenerateRequest,
    ReportRead,
    ReportSummary,
    ReportType,
    ReportUpdate,
)
from app.services.report_service import ReportService

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    responses={
        404: {"model": ErrorResponse, "description": "报告或项目不存在"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
        502: {"model": ErrorResponse, "description": "AI 上游错误"},
        500: {"model": ErrorResponse, "description": "内部错误"},
    },
)


@router.post(
    "/generate",
    response_model=ReportDraft,
    summary="生成报告草稿（不保存，统计由后端计算）",
)
def generate_report(
    payload: ReportGenerateRequest,
    settings: Settings = Depends(get_app_settings),
    service: ReportService = Depends(get_report_service),
) -> ReportDraft:
    return service.generate(payload, use_ai=settings.agent_enabled)


@router.get("", response_model=list[ReportSummary], summary="获取已保存报告列表")
def list_reports(
    report_type: ReportType | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    service: ReportService = Depends(get_report_service),
) -> list[ReportSummary]:
    return service.list_reports(
        report_type=report_type,
        project_id=project_id,
        limit=limit,
    )


@router.post(
    "",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
    summary="保存报告",
)
def save_report(
    payload: ReportCreate,
    service: ReportService = Depends(get_report_service),
) -> ReportRead:
    report = service.save(payload)
    return ReportRead.model_validate(report)


@router.get("/{report_id}", response_model=ReportRead, summary="获取报告详情")
def get_report(
    report_id: UUID,
    service: ReportService = Depends(get_report_service),
) -> ReportRead:
    return service.get_report_view(report_id)


@router.patch("/{report_id}", response_model=ReportRead, summary="修改报告标题或正文")
def update_report(
    report_id: UUID,
    payload: ReportUpdate,
    service: ReportService = Depends(get_report_service),
) -> ReportRead:
    report = service.update_report(report_id, payload)
    return ReportRead.model_validate(report)


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="删除报告",
)
def delete_report(
    report_id: UUID,
    service: ReportService = Depends(get_report_service),
) -> Response:
    service.delete_report(report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{report_id}/markdown",
    response_class=PlainTextResponse,
    summary="导出 Markdown 报告",
)
def export_report(
    report_id: UUID,
    service: ReportService = Depends(get_report_service),
) -> Response:
    report = service.get_report(report_id)
    filename = service.export_filename(report)
    return Response(
        content=service.markdown_export(report),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"taskpilot-report.md\"; filename*=UTF-8''{quote(filename)}"
            )
        },
    )
