"""DOCX / PDF export for saved reports.

Both exporters render the same Markdown that the user can preview and edit.
They produce real files (a WordprocessingML package and a PDF 1.4 document),
not a renamed text file, and they skip any Markdown the renderer cannot honour
instead of inventing content.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.exceptions import ReportNotFoundError
from app.models import Report
from app.repositories.report_repository import ReportRepository

CJK_DOCX_FONT = "宋体"
CJK_PDF_FONT = "STSong-Light"

BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
TABLE_DIVIDER = re.compile(r"^\|[\s:\-|]+\|$")


def _plain(text: str) -> str:
    return BOLD_PATTERN.sub(r"\1", text).replace("`", "")


def _rows(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    index = start
    while index < len(lines) and lines[index].strip().startswith("|"):
        line = lines[index].strip()
        if TABLE_DIVIDER.match(line):
            index += 1
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
        index += 1
    return rows, index


def _blocks(markdown: str):
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            yield ("blank", "")
            index += 1
            continue
        if stripped.startswith("|"):
            rows, index = _rows(lines, index)
            if rows:
                yield ("table", rows)
            continue
        if stripped.startswith("### "):
            yield ("h3", _plain(stripped[4:]))
        elif stripped.startswith("## "):
            yield ("h2", _plain(stripped[3:]))
        elif stripped.startswith("# "):
            yield ("h1", _plain(stripped[2:]))
        elif stripped.startswith(("- ", "* ")):
            yield ("bullet", _plain(stripped[2:]))
        elif stripped.startswith("---"):
            yield ("rule", "")
        else:
            yield ("paragraph", _plain(stripped))
        index += 1


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def build_docx(report: Report) -> bytes:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = CJK_DOCX_FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CJK_DOCX_FONT)

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(report.title)
    run.bold = True
    run.font.size = Pt(18)
    run.font.name = CJK_DOCX_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_DOCX_FONT)

    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta.add_run(
        f"统计范围：{report.period_start:%Y-%m-%d} 至 {report.period_end:%Y-%m-%d}"
        f" · 生成时间：{datetime.now():%Y-%m-%d %H:%M}"
    )
    meta_run.font.size = Pt(9)
    meta_run.font.name = CJK_DOCX_FONT
    meta_run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_DOCX_FONT)

    for kind, value in _blocks(report.content_md):
        if kind == "h1":
            document.add_heading(value, level=0)
        elif kind == "h2":
            document.add_heading(value, level=1)
        elif kind == "h3":
            document.add_heading(value, level=2)
        elif kind == "bullet":
            document.add_paragraph(value, style="List Bullet")
        elif kind == "table":
            if not value:
                continue
            columns = max(len(row) for row in value)
            table = document.add_table(rows=0, cols=columns)
            table.style = "Table Grid"
            for row_index, row in enumerate(value):
                cells = table.add_row().cells
                for column in range(columns):
                    text = row[column] if column < len(row) else ""
                    paragraph = cells[column].paragraphs[0]
                    cell_run = paragraph.add_run(text)
                    cell_run.font.size = Pt(9)
                    cell_run.font.name = CJK_DOCX_FONT
                    cell_run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_DOCX_FONT)
                    if row_index == 0:
                        cell_run.bold = True
        elif kind == "rule":
            document.add_paragraph("—" * 20)
        elif kind == "paragraph":
            paragraph = document.add_paragraph(value)
            paragraph.paragraph_format.space_after = Pt(4)

    footer = document.add_paragraph()
    footer_run = footer.add_run(
        "数据来源：TaskPilot 本地数据库（任务、专注记录、计划时间块、依赖关系）。"
        "统计由后端计算，建议部分不代表预测。"
    )
    footer_run.font.size = Pt(8)
    footer_run.font.name = CJK_DOCX_FONT
    footer_run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_DOCX_FONT)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pdf_text(text: str) -> str:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # CID fonts may lack box-drawing glyphs; ASCII bars stay readable everywhere.
    return safe.replace("█", "*").replace("░", ".")


def build_pdf(report: Report) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont(CJK_PDF_FONT))
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=report.title,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "CJKBody",
        parent=styles["BodyText"],
        fontName=CJK_PDF_FONT,
        fontSize=10,
        leading=15,
    )
    title_style = ParagraphStyle(
        "CJKTitle",
        parent=body,
        fontSize=17,
        leading=23,
        alignment=1,
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "CJKHeading",
        parent=body,
        fontSize=13,
        leading=19,
        spaceBefore=10,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle("CJKMeta", parent=body, fontSize=8.5, leading=12, alignment=1)
    bullet_style = ParagraphStyle("CJKBullet", parent=body, leftIndent=10, bulletIndent=2)

    story: list[object] = [
        Paragraph(_pdf_text(report.title), title_style),
        Paragraph(
            _pdf_text(
                f"统计范围：{report.period_start:%Y-%m-%d} 至 {report.period_end:%Y-%m-%d}"
                f" · 生成时间：{datetime.now():%Y-%m-%d %H:%M}"
            ),
            meta_style,
        ),
        Spacer(1, 6),
    ]

    for kind, value in _blocks(report.content_md):
        if kind == "h1":
            story.append(Paragraph(_pdf_text(value), heading_style))
        elif kind in {"h2", "h3"}:
            story.append(Paragraph(_pdf_text(value), heading_style))
        elif kind == "bullet":
            story.append(Paragraph(_pdf_text(value), bullet_style, bulletText="•"))
        elif kind == "paragraph":
            story.append(Paragraph(_pdf_text(value), body))
        elif kind == "rule":
            story.append(Spacer(1, 4))
        elif kind == "table" and value:
            columns = max(len(row) for row in value)
            data = [
                [
                    Paragraph(_pdf_text(row[index] if index < len(row) else ""), body)
                    for index in range(columns)
                ]
                for row in value
            ]
            table = Table(data, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8a8271")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efe6c6")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            _pdf_text("数据来源：TaskPilot 本地数据库（任务、专注记录、计划时间块、依赖关系）。"),
            meta_style,
        )
    )
    document.build(story)
    return buffer.getvalue()


class ReportExportService:
    """Loads a saved report and returns a real file plus a download name."""

    def __init__(self, session) -> None:
        self.session = session
        self.repository = ReportRepository(session)

    def _load(self, report_id: str) -> Report:
        report = self.repository.get(report_id)
        if report is None:
            raise ReportNotFoundError()
        return report

    @staticmethod
    def _filename(report: Report, suffix: str) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", report.title).strip("_") or "report"
        return f"{safe}_{report.period_start:%Y%m%d}-{report.period_end:%Y%m%d}.{suffix}"

    def docx(self, report_id: str) -> tuple[bytes, str]:
        report = self._load(report_id)
        return build_docx(report), self._filename(report, "docx")

    def pdf(self, report_id: str) -> tuple[bytes, str]:
        report = self._load(report_id)
        return build_pdf(report), self._filename(report, "pdf")
