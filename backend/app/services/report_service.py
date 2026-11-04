"""Report generation: deterministic facts first, AI wording second.

Every number in a report is computed from database rows. The model is only
asked to write the qualitative "problems" and "next steps" sections from those
facts; when the model is unavailable those sections say so instead of inventing
content.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    ProjectNotFoundError,
    ReportNotFoundError,
)
from app.models import Project, Report, Task
from app.repositories.activity_repository import ActivityRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import (
    ReportCreate,
    ReportDraft,
    ReportGenerateRequest,
    ReportRead,
    ReportSummary,
    ReportType,
    ReportUpdate,
)

logger = logging.getLogger("taskpilot.reports")

NarrativeWriter = Callable[[str], str]

PROJECT_STATUS_LABELS = {
    "planning": "规划中",
    "active": "进行中",
    "completed": "已完成",
    "archived": "已归档",
}
PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "弱"}
ACTION_LABELS = {
    "task_created": "创建任务",
    "task_updated": "修改任务",
    "task_completed": "完成任务",
    "task_reopened": "恢复任务",
    "task_deleted": "删除任务",
    "task_project_changed": "调整所属项目",
    "subtask_created": "新增子任务",
    "project_created": "创建项目",
    "project_updated": "修改项目",
    "project_status_changed": "调整项目状态",
}
AI_FALLBACK = "AI 助手未配置或本次生成失败，本节只保留后端统计，没有生成推测性建议。"


class ReportService:
    def __init__(
        self,
        session: Session,
        *,
        timezone: ZoneInfo,
        narrative_writer: NarrativeWriter | None = None,
    ) -> None:
        self.session = session
        self.timezone = timezone
        self.narrative_writer = narrative_writer
        self.task_repository = TaskRepository(session)
        self.project_repository = ProjectRepository(session)
        self.activity_repository = ActivityRepository(session)
        self.report_repository = ReportRepository(session)

    def _rollback(self) -> None:
        try:
            self.session.rollback()
        except SQLAlchemyError:
            pass

    def _commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    # ------------------------------------------------------------------
    # Period handling
    # ------------------------------------------------------------------

    def _local_day_start(self, value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=self.timezone).astimezone(UTC)

    def _period(
        self, request: ReportGenerateRequest, now: datetime
    ) -> tuple[datetime, datetime, Project | None]:
        project: Project | None = None
        if request.project_id is not None:
            project = self.project_repository.get(str(request.project_id))
            if project is None:
                raise ProjectNotFoundError()
        if request.report_type == ReportType.project and project is None:
            raise ProjectNotFoundError()

        if request.period_start is not None and request.period_end is not None:
            return request.period_start, request.period_end, project

        local_now = now.astimezone(self.timezone)
        if request.report_type == ReportType.daily:
            start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            return (
                start_local.astimezone(UTC),
                (start_local + timedelta(days=1)).astimezone(UTC),
                project,
            )
        if request.report_type == ReportType.weekly:
            start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
                days=local_now.weekday()
            )
            return (
                start_local.astimezone(UTC),
                (start_local + timedelta(days=7)).astimezone(UTC),
                project,
            )
        assert project is not None
        if project.start_date is not None:
            start = self._local_day_start(project.start_date)
        else:
            created = [task.created_at for task in self._project_tasks(project.id)]
            start = min(created) if created else self._local_day_start(local_now.date())
        end = now if now > start else start + timedelta(days=1)
        return start, end, project

    # ------------------------------------------------------------------
    # Fact collection
    # ------------------------------------------------------------------

    def _project_tasks(self, project_id: str) -> list[Task]:
        return self.task_repository.list(project_id=project_id)

    def _collect_facts(
        self,
        report_type: ReportType,
        start: datetime,
        end: datetime,
        project: Project | None,
    ) -> dict[str, object]:
        project_id = project.id if project else None
        completed = [
            task
            for task in self.task_repository.completed_between(start, end)
            if project_id is None or task.project_id == project_id
        ]
        created = [
            task
            for task in self.task_repository.created_between(start, end)
            if project_id is None or task.project_id == project_id
        ]
        pending = [
            task
            for task in self.task_repository.list(status="pending", sort_by="due_at", order="asc")
            if project_id is None or task.project_id == project_id
        ]
        now = utc_now()
        overdue = [task for task in pending if task.due_at is not None and task.due_at < now]
        due_in_period = [
            task for task in pending if task.due_at is not None and start <= task.due_at < end
        ]
        upcoming = [task for task in pending if task.due_at is not None and task.due_at >= end][:10]

        touched_project_ids: set[str] = {
            task.project_id for task in completed + created if task.project_id
        }
        if project_id:
            touched_project_ids.add(project_id)
        if report_type in (ReportType.daily, ReportType.weekly):
            for activity in self.activity_repository.list(since=start, until=end, limit=200):
                if activity.project_id:
                    touched_project_ids.add(activity.project_id)

        projects: list[dict[str, object]] = []
        for touched_id in sorted(touched_project_ids):
            touched = self.project_repository.get(touched_id)
            if touched is None:
                continue
            total, completed_count, pending_count, overdue_count = (
                self.task_repository.project_status_counts(touched.id, now=now)
            )
            rate = round(completed_count / total * 100, 1) if total else 0.0
            projects.append(
                {
                    "id": touched.id,
                    "name": touched.name,
                    "status": touched.status,
                    "status_label": PROJECT_STATUS_LABELS.get(touched.status, touched.status),
                    "due_date": touched.due_date.isoformat() if touched.due_date else None,
                    "total_tasks": total,
                    "completed_tasks": completed_count,
                    "pending_tasks": pending_count,
                    "overdue_tasks": overdue_count,
                    "completion_rate": rate,
                }
            )

        activities = self.activity_repository.list(since=start, until=end, limit=200)
        if project_id:
            activities = [item for item in activities if item.project_id == project_id]
        activity_counts = Counter(item.action for item in activities)

        def task_row(task: Task) -> dict[str, object]:
            return {
                "id": task.id,
                "title": task.title,
                "project_id": task.project_id,
                "priority": task.priority,
                "estimated_minutes": task.estimated_minutes,
                "due_at": task.due_at.astimezone(UTC).isoformat() if task.due_at else None,
                "completed_at": (
                    task.completed_at.astimezone(UTC).isoformat() if task.completed_at else None
                ),
                "created_at": task.created_at.astimezone(UTC).isoformat(),
            }

        return {
            "report_type": report_type.value,
            "generated_at": now.astimezone(UTC).isoformat(),
            "timezone": self.timezone.key,
            "period_start": start.astimezone(UTC).isoformat(),
            "period_end": end.astimezone(UTC).isoformat(),
            "period_start_local": start.astimezone(self.timezone).strftime("%Y-%m-%d %H:%M"),
            "period_end_local": end.astimezone(self.timezone).strftime("%Y-%m-%d %H:%M"),
            "project": (
                {
                    "id": project.id,
                    "name": project.name,
                    "status": project.status,
                    "status_label": PROJECT_STATUS_LABELS.get(project.status, project.status),
                    "description": project.description,
                    "start_date": project.start_date.isoformat() if project.start_date else None,
                    "due_date": project.due_date.isoformat() if project.due_date else None,
                }
                if project
                else None
            ),
            "counts": {
                "completed": len(completed),
                "created": len(created),
                "pending": len(pending),
                "overdue": len(overdue),
                "due_in_period": len(due_in_period),
                "activity_records": len(activities),
            },
            "completed_tasks": [task_row(task) for task in completed],
            "created_tasks": [task_row(task) for task in created],
            "pending_tasks": [task_row(task) for task in pending[:20]],
            "overdue_tasks": [task_row(task) for task in overdue[:20]],
            "due_in_period": [task_row(task) for task in due_in_period[:20]],
            "upcoming_tasks": [task_row(task) for task in upcoming],
            "projects": projects,
            "activity_counts": dict(activity_counts),
            "activities": [
                {
                    "action": item.action,
                    "summary": item.summary,
                    "task_title": item.task_title,
                    "project_name": item.project_name,
                    "created_at": item.created_at.astimezone(UTC).isoformat(),
                }
                for item in activities[:30]
            ],
        }

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def _project_name_map(self) -> dict[str, str]:
        return {project.id: project.name for project in self.project_repository.list()}

    def _task_line(self, row: dict[str, object], names: dict[str, str]) -> str:
        parts: list[str] = [str(row["title"])]
        project_id = row.get("project_id")
        if project_id:
            parts.append(names.get(str(project_id), "未知项目"))
        parts.append(f"优先级{PRIORITY_LABELS.get(str(row.get('priority')), '中')}")
        if row.get("due_at"):
            due = datetime.fromisoformat(str(row["due_at"])).astimezone(self.timezone)
            parts.append(f"截止 {due.strftime('%m-%d %H:%M')}")
        if row.get("completed_at"):
            done = datetime.fromisoformat(str(row["completed_at"])).astimezone(self.timezone)
            parts.append(f"完成于 {done.strftime('%m-%d %H:%M')}")
        return f"- 「{parts[0]}」· " + " · ".join(parts[1:])

    def _facts_lines(self, facts: dict[str, object], names: dict[str, str]) -> dict[str, list[str]]:
        completed = facts["completed_tasks"]
        created = facts["created_tasks"]
        pending = facts["pending_tasks"]
        overdue = facts["overdue_tasks"]
        due_in_period = facts["due_in_period"]
        assert isinstance(completed, list)
        assert isinstance(created, list)
        assert isinstance(pending, list)
        assert isinstance(overdue, list)
        assert isinstance(due_in_period, list)
        return {
            "completed": [self._task_line(row, names) for row in completed],
            "created": [self._task_line(row, names) for row in created],
            "pending": [self._task_line(row, names) for row in pending],
            "overdue": [self._task_line(row, names) for row in overdue],
            "due_in_period": [self._task_line(row, names) for row in due_in_period],
        }

    def _header(self, facts: dict[str, object]) -> list[str]:
        return [
            f"> 统计范围：{facts['period_start_local']} 至 {facts['period_end_local']}"
            f"（{facts['timezone']}）",
            "> 数据来源：TaskPilot 真实任务与活动记录；统计数字由后端计算。",
            "",
        ]

    def _render_markdown(
        self,
        facts: dict[str, object],
        *,
        report_type: ReportType,
        title: str,
        names: dict[str, str],
        problems: str,
        suggestions: str,
    ) -> str:
        lines = self._facts_lines(facts, names)
        counts = facts["counts"]
        assert isinstance(counts, dict)
        body: list[str] = [f"# {title}", *self._header(facts)]

        if report_type == ReportType.project:
            project = facts["project"]
            assert isinstance(project, dict)
            body += [
                "## 一、项目基本信息",
                f"- 项目名称：{project['name']}",
                f"- 项目状态：{project.get('status_label', project['status'])}",
                f"- 开始日期：{project.get('start_date') or '未设置'}",
                f"- 截止日期：{project.get('due_date') or '未设置'}",
                f"- 项目描述：{project.get('description') or '未填写'}",
                "",
                "## 二、整体进度",
                (
                    f"- 统计期内完成 {counts['completed']} 项，新建 {counts['created']} 项；"
                    f"当前待完成 {counts['pending']} 项，逾期 {counts['overdue']} 项。"
                ),
            ]
            projects = facts["projects"]
            assert isinstance(projects, list)
            for item in projects:
                if not isinstance(item, dict):
                    continue
                body.append(
                    f"- 「{item['name']}」完成 {item['completed_tasks']}/{item['total_tasks']}"
                    f"（{item['completion_rate']}%）"
                )
            body += ["", "## 三、已完成任务（统计期内）"]
            body += lines["completed"] or ["- 统计期内没有已完成任务。"]
            body += ["", "## 四、当前待办任务"]
            body += lines["pending"] or ["- 当前没有待办任务。"]
            body += ["", "## 五、逾期及阻塞情况"]
            body += lines["overdue"] or ["- 当前没有逾期任务。"]
            body += [
                "",
                "## 六、后续工作建议",
                "### 存在的问题",
                problems,
                "",
                "### 后续建议",
                suggestions,
            ]
            project_next = facts["upcoming_tasks"]
            assert isinstance(project_next, list)
            body += ["", "### 后续待办（按截止时间）"]
            body += (
                [self._task_line(row, names) for row in project_next]
                if project_next
                else ["- 没有带截止时间的后续待办任务。"]
            )
        else:
            scope = "本周" if report_type == ReportType.weekly else "今日"
            body += [
                f"## 一、{scope}工作概览",
                (
                    f"- {scope}完成 {counts['completed']} 项任务，"
                    f"新建 {counts['created']} 项；"
                    f"当前待完成 {counts['pending']} 项，其中逾期 {counts['overdue']} 项。"
                ),
                f"- 统计期内到期但未完成：{counts['due_in_period']} 项。",
                "",
                f"## 二、{scope}已完成工作",
            ]
            body += lines["completed"] or ["- 统计期内没有已完成任务。"]
            body += ["", "## 三、重点项目进度"]
            projects = facts["projects"]
            assert isinstance(projects, list)
            if projects:
                for item in projects:
                    assert isinstance(item, dict)
                    body.append(
                        f"- 「{item['name']}」（{item.get('status_label', item['status'])}）："
                        f"完成 {item['completed_tasks']}/{item['total_tasks']}"
                        f"（{item['completion_rate']}%），"
                        f"待完成 {item['pending_tasks']} 项，逾期 {item['overdue_tasks']} 项"
                    )
            else:
                body.append("- 统计期内没有关联项目。")
            body += ["", "## 四、未完成及延期事项"]
            if lines["overdue"]:
                body.append("逾期任务：")
                body += lines["overdue"]
            if lines["due_in_period"]:
                body.append("统计期内到期但未完成：")
                body += lines["due_in_period"]
            pending_rows = facts["pending_tasks"]
            assert isinstance(pending_rows, list)
            overdue_ids = {row.get("id") for row in facts["overdue_tasks"] if isinstance(row, dict)}
            due_ids = {row.get("id") for row in facts["due_in_period"] if isinstance(row, dict)}
            remaining = [
                self._task_line(row, names)
                for row in pending_rows
                if isinstance(row, dict)
                and row.get("id") not in overdue_ids
                and row.get("id") not in due_ids
            ]
            if remaining:
                body.append("其他待完成：")
                body += remaining
            if not lines["overdue"] and not lines["due_in_period"] and not remaining:
                body.append("- 没有逾期或统计期内到期的未完成任务。")
            body += [
                "",
                "## 五、存在的问题",
                problems,
                "",
                f"## 六、{scope}之后的工作计划",
            ]
            upcoming = facts["upcoming_tasks"]
            assert isinstance(upcoming, list)
            body += (
                [self._task_line(row, names) for row in upcoming]
                if upcoming
                else ["- 没有带截止时间的后续待办任务；可在任务列表中补充计划。"]
            )
            body += ["", "### 后续建议", suggestions]

        body += [
            "",
            "---",
            "*本报告由 TaskPilot 生成：客观统计来自真实数据库记录，"
            "AI 仅参与文字组织与建议，不修改事实。*",
            "",
        ]
        return "\n".join(body)

    # ------------------------------------------------------------------
    # AI narrative
    # ------------------------------------------------------------------

    def _narrative_prompt(self, facts: dict[str, object]) -> str:
        compact = json.dumps(facts, ensure_ascii=False, default=str)
        if len(compact) > 12_000:
            compact = compact[:12_000] + "…（截断）"
        return (
            "你是 TaskPilot 的工作报告助手。下面 JSON 是后端根据数据库计算出的真实事实。\n"
            "严格规则：\n"
            "1. 只能使用 JSON 中的任务、项目、数字与日期；不得编造任何任务或数字。\n"
            "2. 不要修改、重算或推测统计数字；没有数据时明确说明没有数据。\n"
            "3. 输出中文纯文本，分成两节，标题分别为「存在的问题」和「后续建议」。\n"
            "4. 每节 2-4 条，每条以「- 」开头，简洁具体，不要输出其他内容。\n"
            f"事实 JSON：\n{compact}"
        )

    def _narrative(self, facts: dict[str, object], *, enabled: bool) -> tuple[str, str, bool]:
        if not enabled or self.narrative_writer is None:
            return AI_FALLBACK, AI_FALLBACK, False
        try:
            raw = self.narrative_writer(self._narrative_prompt(facts)).strip()
        except Exception as exc:  # noqa: BLE001 - AI failures must not break reports
            logger.warning("Report narrative generation failed: %s", type(exc).__name__)
            return AI_FALLBACK, AI_FALLBACK, False
        if not raw:
            return AI_FALLBACK, AI_FALLBACK, False
        problems, suggestions = self._split_narrative(raw)
        return problems, suggestions, True

    @staticmethod
    def _split_narrative(raw: str) -> tuple[str, str]:
        text = raw.strip()
        split_at = -1
        for marker in ("后续建议", "下一步建议", "建议："):
            index = text.find(marker)
            if index > 0:
                split_at = index
                break
        if split_at < 0:
            return text or AI_FALLBACK, "（AI 未单独给出建议节。）"
        problems = text[:split_at]
        suggestions = text[split_at:]
        for marker in ("存在的问题：", "存在的问题:", "存在的问题"):
            problems = problems.replace(marker, "")
        for marker in ("后续建议：", "后续建议:", "后续建议", "下一步建议：", "下一步建议"):
            suggestions = suggestions.replace(marker, "")
        cleaned_problems = "\n".join(line for line in problems.splitlines() if line.strip()).strip()
        cleaned_suggestions = "\n".join(
            line for line in suggestions.splitlines() if line.strip()
        ).strip()
        return (
            cleaned_problems or AI_FALLBACK,
            cleaned_suggestions or "（AI 未给出具体建议。）",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        request: ReportGenerateRequest,
        *,
        use_ai: bool = True,
        now: datetime | None = None,
    ) -> ReportDraft:
        now = now or utc_now()
        start, end, project = self._period(request, now)
        facts = self._collect_facts(request.report_type, start, end, project)
        title = self._title(request.report_type, start, end, project)
        names = self._project_name_map()
        problems, suggestions, ai_used = self._narrative(facts, enabled=use_ai)
        content = self._render_markdown(
            facts,
            report_type=request.report_type,
            title=title,
            names=names,
            problems=problems,
            suggestions=suggestions,
        )
        return ReportDraft(
            report_type=request.report_type,
            title=title,
            period_start=start,
            period_end=end,
            project_id=UUID(project.id) if project else None,
            project_name=project.name if project else None,
            content_md=content,
            facts=facts,
            ai_used=ai_used,
        )

    def _title(
        self,
        report_type: ReportType,
        start: datetime,
        end: datetime,
        project: Project | None,
    ) -> str:
        local_start = start.astimezone(self.timezone)
        local_end = (end - timedelta(seconds=1)).astimezone(self.timezone)
        if report_type == ReportType.project and project is not None:
            return f"「{project.name}」进度报告（截至 {local_end.date().isoformat()}）"
        if report_type == ReportType.weekly:
            iso_year, iso_week, _ = local_start.isocalendar()
            return (
                f"{iso_year} 年第 {iso_week} 周工作周报"
                f"（{local_start.date().isoformat()} 至 {local_end.date().isoformat()}）"
            )
        return f"{local_start.date().isoformat()} 工作日报"

    def save(self, draft: ReportCreate, *, commit: bool = True) -> Report:
        project = None
        if draft.project_id is not None:
            project = self.project_repository.get(str(draft.project_id))
            if project is None:
                raise ProjectNotFoundError()
        report = Report(
            report_type=draft.report_type.value,
            title=draft.title,
            period_start=draft.period_start,
            period_end=draft.period_end,
            project_id=str(project.id) if project else None,
            project_name=project.name if project else None,
            content_md=draft.content_md,
            facts=draft.facts,
            ai_used=draft.ai_used,
        )
        try:
            self.report_repository.add(report)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        if commit:
            self._commit()
        return report

    def save_draft(self, draft: ReportDraft, *, commit: bool = True) -> Report:
        return self.save(
            ReportCreate(
                report_type=draft.report_type,
                title=draft.title,
                period_start=draft.period_start,
                period_end=draft.period_end,
                project_id=draft.project_id,
                content_md=draft.content_md,
                facts=draft.facts,
                ai_used=draft.ai_used,
            ),
            commit=commit,
        )

    def list_reports(
        self,
        *,
        report_type: ReportType | None = None,
        project_id: str | UUID | None = None,
        limit: int = 50,
    ) -> list[ReportSummary]:
        reports = self.report_repository.list(
            report_type=report_type.value if report_type else None,
            project_id=str(project_id) if project_id else None,
            limit=max(1, min(limit, 100)),
        )
        return [ReportSummary.model_validate(report) for report in reports]

    def get_report(self, report_id: str | UUID) -> Report:
        report = self.report_repository.get(str(report_id))
        if report is None:
            raise ReportNotFoundError()
        return report

    def get_report_view(self, report_id: str | UUID) -> ReportRead:
        return ReportRead.model_validate(self.get_report(report_id))

    def update_report(
        self, report_id: str | UUID, data: ReportUpdate, *, commit: bool = True
    ) -> Report:
        report = self.get_report(report_id)
        fields = data.model_dump(exclude_unset=True)
        if "title" in fields and fields["title"] is not None:
            report.title = str(fields["title"]).strip()
        if "content_md" in fields and fields["content_md"] is not None:
            report.content_md = str(fields["content_md"]).strip()
        report.updated_at = utc_now()
        if commit:
            self._commit()
        else:
            try:
                self.session.flush()
            except SQLAlchemyError as exc:
                self._rollback()
                raise DatabaseOperationError() from exc
        return report

    def delete_report(self, report_id: str | UUID, *, commit: bool = True) -> None:
        report = self.get_report(report_id)
        try:
            self.report_repository.delete(report)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        if commit:
            self._commit()

    @staticmethod
    def markdown_export(report: Report) -> str:
        return report.content_md

    @staticmethod
    def export_filename(report: Report) -> str:
        safe = "".join(
            char if char.isalnum() or char in ("-", "_", "（", "）", "「", "」") else "_"
            for char in report.title
        )
        return f"{safe.strip('_') or 'taskpilot-report'}.md"
