"""Enhanced V2.0 reports and DOCX/PDF export endpoints."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_report_export_service, get_report_v2_service
from app.schemas import ErrorResponse, ReportDraft, ReportType
from app.schemas_v2 import EnhancedReportRequest
from app.services.report_export_service import ReportExportService
from app.services.report_v2_service import ReportV2Service

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    responses={
        404: {"model": ErrorResponse, "description": "报告不存在"},
        422: {"model": ErrorResponse, "description": "输入校验失败"},
        503: {"model": ErrorResponse, "description": "导出组件不可用"},
    },
)

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA = "application/pdf"


@router.post(
    "/enhanced",
    response_model=ReportDraft,
    summary="生成增强报告草稿（真实工作时长、计划对比、趋势与风险）",
)
def generate_enhanced(
    payload: EnhancedReportRequest,
    service: ReportV2Service = Depends(get_report_v2_service),
) -> ReportDraft:
    return service.generate(
        report_type=ReportType(payload.report_type),
        period_start=payload.period_start,
        period_end=payload.period_end,
        project_id=str(payload.project_id) if payload.project_id else None,
        template=payload.template,
    )


def _download(content: bytes, media_type: str, filename: str) -> Response:
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (f"attachment; filename=\"report\"; filename*=UTF-8''{encoded}")
        },
    )


@router.get("/{report_id}/docx", summary="导出 Word 文档")
def export_docx(
    report_id: UUID,
    service: ReportExportService = Depends(get_report_export_service),
) -> Response:
    content, filename = service.docx(str(report_id))
    return _download(content, DOCX_MEDIA, filename)


@router.get("/{report_id}/pdf", summary="导出 PDF 文档")
def export_pdf(
    report_id: UUID,
    service: ReportExportService = Depends(get_report_export_service),
) -> Response:
    content, filename = service.pdf(str(report_id))
    return _download(content, PDF_MEDIA, filename)
