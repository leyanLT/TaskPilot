"""LangChain tools exposed to the TaskPilot agent.

Every tool calls a Service. Tools never touch the database, and every write only
produces a pending action that requires a separate user confirmation. v1.5 adds
projects, subtasks, priority insight, daily planning, activities, and reports.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field, ValidationError

from app.database import utc_now
from app.exceptions import AppError, PlanConflictError
from app.models import Task
from app.schemas import (
    BreakdownDraft,
    BreakdownSubtaskDraft,
    BreakdownTaskDraft,
    PlanDraft,
    PlanDraftItem,
    PlanItemInput,
    ProjectRead,
    ReportGenerateRequest,
    ReportType,
    TaskChanges,
    TaskCreate,
    TaskPriority,
    TaskRead,
    TaskStatus,
)
from app.services.activity_service import PRIORITY_LABELS, ActivityService
from app.services.dependency_service import DependencyService
from app.services.focus_service import FocusService
from app.services.insight_service import InsightService
from app.services.pending_action_service import (
    MAX_BATCH_CREATE,
    MAX_BATCH_RESCHEDULE,
    PendingActionService,
)
from app.services.planning_service import PlanningService
from app.services.priority_service import PriorityService
from app.services.project_service import ProjectService
from app.services.replan_service import ReplanService
from app.services.report_service import ReportService
from app.services.task_service import TaskService

logger = logging.getLogger("taskpilot.agent.tools")

PROJECT_STATUS_LABELS = {
    "planning": "规划中",
    "active": "进行中",
    "completed": "已完成",
    "archived": "已归档",
}


class CreateTaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    due_at: str | None = None
    project_id: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=1440)


class BreakdownSubtaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    priority: Literal["high", "medium", "low"] = "medium"
    estimated_minutes: int | None = Field(default=None, ge=5, le=1440)
    due_at: str | None = None


class BreakdownTaskInput(BreakdownSubtaskInput):
    subtasks: list[BreakdownSubtaskInput] = Field(default_factory=list)


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _parse_due_at(value: str | None, timezone: ZoneInfo) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("due_at 必须是 ISO 8601 日期时间，例如 2026-11-04T15:00:00+08:00") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _parse_plan_date(value: str | None, timezone: ZoneInfo) -> date:
    if value is None or not value.strip():
        return utc_now().astimezone(timezone).date()
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("plan_date 必须是 YYYY-MM-DD 格式的日期") from exc


def _uuid_or_none(value: str | None, label: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise ValueError(f"{label} 不是有效的 ID") from exc


def _local(value: datetime | None, timezone: ZoneInfo) -> str | None:
    return value.astimezone(timezone).isoformat() if value else None


def _local_format(value: datetime, timezone: ZoneInfo) -> str:
    return value.astimezone(timezone).strftime("%m月%d日 %H:%M")


class TaskToolset:
    """Builds request-scoped tools and guards against duplicate side effects."""

    def __init__(
        self,
        task_service: TaskService,
        action_service: PendingActionService,
        *,
        timezone: ZoneInfo,
        project_service: ProjectService | None = None,
        planning_service: PlanningService | None = None,
        priority_service: PriorityService | None = None,
        activity_service: ActivityService | None = None,
        report_service: ReportService | None = None,
        dependency_service: DependencyService | None = None,
        focus_service: FocusService | None = None,
        insight_service: InsightService | None = None,
        replan_service: ReplanService | None = None,
    ) -> None:
        self.task_service = task_service
        self.action_service = action_service
        self.timezone = timezone
        self.project_service = project_service or ProjectService(
            task_service.session, timezone=timezone
        )
        self.planning_service = planning_service or PlanningService(
            task_service.session, timezone=timezone
        )
        self.priority_service = priority_service or PriorityService(
            task_service.session, timezone=timezone
        )
        self.activity_service = activity_service or ActivityService(
            task_service.session, timezone=timezone
        )
        self.report_service = report_service or ReportService(
            task_service.session, timezone=timezone
        )
        self.dependency_service = dependency_service or DependencyService(task_service.session)
        self.focus_service = focus_service or FocusService(task_service.session, timezone=timezone)
        self.insight_service = insight_service or InsightService(
            task_service.session, timezone=timezone
        )
        self.replan_service = replan_service or ReplanService(
            task_service.session, timezone=timezone
        )
        self._state = {
            "draft_created": False,
            "ambiguity_blocked": False,
        }
        self._project_cache: dict[str, dict[str, object]] = {}

    # ------------------------------------------------------------------
    # Shared presentation helpers
    # ------------------------------------------------------------------

    def _project_brief(self, project_id: str | None) -> dict[str, object] | None:
        if not project_id:
            return None
        if project_id in self._project_cache:
            return self._project_cache[project_id]
        try:
            project = self.project_service.get_project(project_id)
        except AppError:
            return None
        brief = {
            "id": project.id,
            "name": project.name,
            "status": project.status,
            "status_label": PROJECT_STATUS_LABELS.get(project.status, project.status),
            "due_date": project.due_date.isoformat() if project.due_date else None,
        }
        self._project_cache[project_id] = brief
        return brief

    def _task_summary(self, task: Task | TaskRead) -> dict[str, object]:
        now = utc_now()
        due_at = task.due_at
        project = self._project_brief(str(task.project_id) if task.project_id else None)
        total, completed = (
            (task.subtask_count, task.completed_subtask_count)
            if isinstance(task, TaskRead)
            else self.task_service.subtask_counts(task.id)
        )
        return {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": str(task.status),
            "priority": str(task.priority),
            "priority_label": PRIORITY_LABELS.get(str(task.priority), "中"),
            "estimated_minutes": task.estimated_minutes,
            "project_id": str(task.project_id) if task.project_id else None,
            "project_name": project["name"] if project else None,
            "parent_id": str(task.parent_id) if task.parent_id else None,
            "subtask_count": total,
            "completed_subtask_count": completed,
            "due_at": due_at.astimezone(UTC).isoformat() if due_at else None,
            "due_at_local": _local(due_at, self.timezone),
            "completed_at": _local(task.completed_at, self.timezone),
            "is_overdue": bool(
                due_at is not None and task.status == TaskStatus.pending.value and due_at < now
            ),
        }

    def _candidate(self, task: Task) -> dict[str, object]:
        summary = self._task_summary(task)
        return {
            "id": summary["id"],
            "title": summary["title"],
            "due_at": summary["due_at"],
            "status": summary["status"],
        }

    def _project_summary(self, project_view: ProjectRead) -> dict[str, object]:
        stats = project_view.stats
        return {
            "id": str(project_view.id),
            "name": project_view.name,
            "status": project_view.status.value,
            "status_label": PROJECT_STATUS_LABELS.get(
                project_view.status.value, project_view.status.value
            ),
            "description": project_view.description,
            "start_date": (
                project_view.start_date.isoformat() if project_view.start_date else None
            ),
            "due_date": (project_view.due_date.isoformat() if project_view.due_date else None),
            "total_tasks": stats.total_tasks,
            "completed_tasks": stats.completed_tasks,
            "pending_tasks": stats.pending_tasks,
            "overdue_tasks": stats.overdue_tasks,
            "completion_rate": stats.completion_rate,
        }

    def _change_summary(self, task: Task, changes: TaskChanges) -> str:
        parts: list[str] = []
        if "title" in changes.model_fields_set:
            parts.append(f"标题改为「{changes.title}」")
        if "description" in changes.model_fields_set:
            parts.append("更新描述" if changes.description else "清空描述")
        if "due_at" in changes.model_fields_set:
            if changes.due_at:
                parts.append(f"截止时间改为 {_local_format(changes.due_at, self.timezone)}")
            else:
                parts.append("取消截止时间")
        if "priority" in changes.model_fields_set and changes.priority:
            parts.append(f"优先级改为{PRIORITY_LABELS.get(changes.priority.value, '中')}")
        if "estimated_minutes" in changes.model_fields_set:
            if changes.estimated_minutes:
                parts.append(f"预计耗时改为 {changes.estimated_minutes} 分钟")
            else:
                parts.append("清空预计耗时")
        if "project_id" in changes.model_fields_set:
            if changes.project_id:
                project = self._project_brief(str(changes.project_id))
                parts.append(
                    f"所属项目改为「{project['name'] if project else changes.project_id}」"
                )
            else:
                parts.append("移出当前项目")
        return f"修改任务「{task.title}」：" + "，".join(parts)

    def _breakdown_draft(
        self,
        goal: str,
        project_id: str | None,
        tasks: list[BreakdownTaskInput],
    ) -> tuple[BreakdownDraft, list[str]]:
        project = self._project_brief(project_id)
        draft_tasks: list[BreakdownTaskDraft] = []
        warnings: list[str] = []
        project_due = None
        if project_id:
            project_model = self.project_service.get_project(project_id)
            if project_model.status == "archived":
                raise ValueError("项目已归档，不能向其添加任务。请先恢复项目。")
            project_due = project_model.due_date

        today = utc_now().astimezone(self.timezone).date()
        if project_due is not None and project_due < today:
            warnings.append("项目截止日期已经过去，新任务会落在项目截止之后。")

        total_minutes = 0
        for item in tasks:
            due_at = _parse_due_at(item.due_at, self.timezone)
            if due_at is not None and due_at < utc_now():
                warnings.append(f"任务「{item.title}」的截止时间已经过去。")
            if project_due is not None and due_at is not None:
                if due_at.astimezone(self.timezone).date() > project_due:
                    warnings.append(
                        f"任务「{item.title}」的截止时间晚于项目截止日期 {project_due.isoformat()}。"
                    )
            subtasks: list[BreakdownSubtaskDraft] = []
            for subtask in item.subtasks:
                subtask_due = _parse_due_at(subtask.due_at, self.timezone)
                if subtask_due is not None and subtask_due < utc_now():
                    warnings.append(f"子任务「{subtask.title}」的截止时间已经过去。")
                if project_due is not None and subtask_due is not None:
                    if subtask_due.astimezone(self.timezone).date() > project_due:
                        warnings.append(f"子任务「{subtask.title}」的截止时间晚于项目截止日期。")
                if subtask.estimated_minutes:
                    total_minutes += subtask.estimated_minutes
                subtasks.append(
                    BreakdownSubtaskDraft(
                        title=subtask.title,
                        description=subtask.description,
                        priority=TaskPriority(subtask.priority),
                        estimated_minutes=subtask.estimated_minutes,
                        due_at=subtask_due,
                    )
                )
            if item.estimated_minutes:
                total_minutes += item.estimated_minutes
            draft_tasks.append(
                BreakdownTaskDraft(
                    title=item.title,
                    description=item.description,
                    priority=TaskPriority(item.priority),
                    estimated_minutes=item.estimated_minutes,
                    due_at=due_at,
                    subtasks=subtasks,
                )
            )

        if project_due is not None:
            remaining_days = max(1, (project_due - today).days + 1)
            capacity = remaining_days * 480
            if total_minutes > capacity:
                warnings.append(
                    f"拆解任务预计共 {total_minutes} 分钟，超过项目剩余 {remaining_days} 天"
                    f"按每天 8 小时估算的 {capacity} 分钟，时间安排可能不可行。"
                )
        draft = BreakdownDraft(
            goal=goal,
            project_id=UUID(project_id) if project_id else None,
            project_name=str(project["name"]) if project else None,
            tasks=draft_tasks,
        )
        return draft, warnings

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def build(self) -> list[BaseTool]:
        state = self._state

        def already_busy() -> str | None:
            if state["draft_created"]:
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "本轮已生成待确认操作，请先处理当前操作。",
                    }
                )
            if state["ambiguity_blocked"]:
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "存在多个匹配任务，必须等用户明确选择或补充标题后再操作。",
                    }
                )
            return None

        def ambiguous_result(
            matches: list[Task],
            *,
            action_label: str,
            query: str,
        ) -> str:
            state["ambiguity_blocked"] = True
            return _json(
                {
                    "ok": True,
                    "kind": "needs_disambiguation",
                    "matches": [self._candidate(task) for task in matches],
                    "message": (
                        f"找到 {len(matches)} 个与「{query.strip()}」匹配的任务，"
                        f"请让用户补充更精确的标题后再{action_label}。"
                    ),
                }
            )

        @tool
        def query_tasks(
            status: Literal["all", "pending", "completed"] = "all",
            search: str | None = None,
            project_id: str | None = None,
            priority: Literal["high", "medium", "low", "all"] = "all",
            include_subtasks: bool = True,
        ) -> str:
            """Read real tasks from the database. Use this before answering any
            question about tasks or planning work. Filters: status (all/pending/
            completed), title search, project_id, priority. include_subtasks
            controls whether subtasks are listed separately."""
            try:
                selected_status = None if status == "all" else TaskStatus(status)
                selected_priority = None if priority == "all" else TaskPriority(priority)
                parsed_project = _uuid_or_none(project_id, "project_id")
                tasks = self.task_service.list_tasks(
                    status=selected_status,
                    project_id=parsed_project,
                    priority=selected_priority,
                )
                if search and search.strip():
                    keyword = search.strip().casefold()
                    tasks = [task for task in tasks if keyword in task.title.casefold()]
                if not include_subtasks:
                    tasks = [task for task in tasks if task.parent_id is None]
                summaries = [self._task_summary(task) for task in tasks]
                return _json(
                    {
                        "ok": True,
                        "kind": "tasks",
                        "count": len(summaries),
                        "tasks": summaries,
                        "message": f"从数据库读取到 {len(summaries)} 个任务。",
                    }
                )
            except Exception as exc:
                logger.warning("query_tasks failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取任务失败，请稍后重试。",
                    }
                )

        @tool
        def query_projects(
            status: Literal["all", "planning", "active", "completed", "archived"] = "all",
            search: str | None = None,
        ) -> str:
            """Read real projects with task counts and completion rate. Use this
            before assigning tasks to a project or writing a project report."""
            try:
                from app.schemas import ProjectStatus

                selected = None if status == "all" else ProjectStatus(status)
                projects = self.project_service.list_projects(
                    status=selected,
                    include_archived=status in ("all", "archived"),
                    search=search,
                )
                summaries = [self._project_summary(project) for project in projects]
                return _json(
                    {
                        "ok": True,
                        "kind": "projects",
                        "count": len(summaries),
                        "projects": summaries,
                        "message": f"从数据库读取到 {len(summaries)} 个项目。",
                    }
                )
            except Exception as exc:
                logger.warning("query_projects failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取项目失败，请稍后重试。",
                    }
                )

        @tool
        def get_task_subtasks(query: str) -> str:
            """Read one task and its subtasks to explain the hierarchy or check
            progress. query is a task title (or exact ID). If several tasks
            match, the candidates are returned instead of choosing one."""
            if not query.strip():
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "请提供任务标题。",
                    }
                )
            try:
                matches = self.task_service.search_tasks(query)
                if not matches:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": f"没有找到标题包含「{query.strip()}」的任务。",
                        }
                    )
                selected, ambiguous = _select_unique(matches, query)
                if selected is None:
                    return _json(
                        {
                            "ok": True,
                            "kind": "needs_disambiguation",
                            "matches": [self._candidate(task) for task in ambiguous],
                            "message": f"找到 {len(ambiguous)} 个匹配任务，请明确选择。",
                        }
                    )
                detail = self.task_service.get_task_detail(selected.id)
                return _json(
                    {
                        "ok": True,
                        "kind": "task_detail",
                        "task": self._task_summary(selected),
                        "subtasks": [self._task_summary(subtask) for subtask in detail.subtasks],
                        "progress": f"{detail.completed_subtask_count}/{detail.subtask_count}",
                        "message": (
                            f"「{selected.title}」共有 {detail.subtask_count} 个子任务，"
                            f"已完成 {detail.completed_subtask_count} 个。"
                        ),
                    }
                )
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("get_task_subtasks failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取子任务失败，请稍后重试。",
                    }
                )

        @tool
        def get_agenda(period: Literal["today", "week"] = "today") -> str:
            """Read a real-data agenda for daily planning or a review. period
            today returns overdue, due-today and recently completed tasks;
            period week returns this week's due and completed tasks. Never
            invent tasks or totals when answering."""
            try:
                now = utc_now()
                local_now = now.astimezone(self.timezone)
                day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = day_start - timedelta(days=day_start.weekday())
                week_end = week_start + timedelta(days=7)

                pending = self.task_service.list_tasks(status=TaskStatus.pending)
                completed = self.task_service.list_tasks(status=TaskStatus.completed)

                def due_local(task: Task) -> datetime | None:
                    return task.due_at.astimezone(self.timezone) if task.due_at else None

                overdue = [
                    task for task in pending if task.due_at is not None and task.due_at < now
                ]
                due_today = [
                    task
                    for task in pending
                    if due_local(task) is not None and due_local(task).date() == local_now.date()
                ]
                due_this_week = [
                    task
                    for task in pending
                    if due_local(task) is not None and week_start <= due_local(task) < week_end
                ]

                def completed_local(task: Task) -> datetime:
                    return task.completed_at or task.updated_at

                completed_today = [
                    task
                    for task in completed
                    if completed_local(task).astimezone(self.timezone).date() == local_now.date()
                ]
                completed_this_week = [
                    task
                    for task in completed
                    if week_start <= completed_local(task).astimezone(self.timezone) < week_end
                ]
                upcoming = sorted(
                    [task for task in pending if task.due_at is not None and task.due_at >= now],
                    key=lambda task: task.due_at or now,
                )[:8]

                if period == "today":
                    focus = due_today + [task for task in overdue if task not in due_today]
                    complete_scope = completed_today
                else:
                    focus = due_this_week
                    complete_scope = completed_this_week

                return _json(
                    {
                        "ok": True,
                        "kind": "agenda",
                        "period": period,
                        "counts": {
                            "pending": len(pending),
                            "overdue": len(overdue),
                            "due_today": len(due_today),
                            "due_this_week": len(due_this_week),
                            "completed_today": len(completed_today),
                            "completed_this_week": len(completed_this_week),
                        },
                        "focus": [self._task_summary(task) for task in focus],
                        "overdue": [self._task_summary(task) for task in overdue],
                        "due_today": [self._task_summary(task) for task in due_today],
                        "due_this_week": [self._task_summary(task) for task in due_this_week],
                        "completed": [self._task_summary(task) for task in complete_scope],
                        "upcoming": [self._task_summary(task) for task in upcoming],
                        "message": f"已读取 {period} 的真实任务数据。",
                    }
                )
            except Exception as exc:
                logger.exception("get_agenda failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取日程失败，请稍后重试。",
                    }
                )

        @tool
        def get_priority_suggestions(
            limit: int = 5,
            project_id: str | None = None,
        ) -> str:
            """Read deterministic priority suggestions computed from the user's
            priority, deadlines, overdue state, effort, and project dates. Use
            the returned reasons to explain the advice; never invent reasons.
            This never changes a task's priority."""
            try:
                parsed_project = _uuid_or_none(project_id, "project_id")
                suggestions = self.priority_service.suggestions(
                    limit=max(1, min(limit, 20)),
                    project_id=parsed_project,
                )
                payload = [
                    {
                        "task_id": str(item.task_id),
                        "title": item.title,
                        "current_priority": item.current_priority.value,
                        "current_priority_label": PRIORITY_LABELS.get(
                            item.current_priority.value, "中"
                        ),
                        "suggested_priority": item.suggested_priority.value,
                        "suggested_priority_label": PRIORITY_LABELS.get(
                            item.suggested_priority.value, "中"
                        ),
                        "score": item.score,
                        "reasons": item.reasons,
                        "project_name": item.project_name,
                        "due_at_local": _local(item.due_at, self.timezone),
                        "estimated_minutes": item.estimated_minutes,
                    }
                    for item in suggestions
                ]
                return _json(
                    {
                        "ok": True,
                        "kind": "priority_suggestions",
                        "count": len(payload),
                        "suggestions": payload,
                        "message": (
                            f"已根据真实任务数据生成 {len(payload)} 条优先级建议；"
                            "调整仍需用户确认。"
                        ),
                    }
                )
            except Exception as exc:
                logger.exception("get_priority_suggestions failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成优先级建议失败，请稍后重试。",
                    }
                )

        @tool
        def get_planning_context(
            available_minutes: int,
            plan_date: str | None = None,
        ) -> str:
            """Read the real capacity-bounded task proposal for a day. Returns
            suggested time blocks with task IDs, start/end times, and reasons,
            plus any existing plan. Use these blocks when preparing a daily
            plan; never schedule invented tasks or exceed the available time."""
            if not 5 <= available_minutes <= 1440:
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "可用时间必须在 5-1440 分钟之间。",
                    }
                )
            try:
                target_date = _parse_plan_date(plan_date, self.timezone)
                existing = self.planning_service.get_plan_or_none(target_date)
                blocks = self.planning_service.suggest_blocks(target_date, available_minutes)
                payload = [
                    {
                        "task_id": str(block["task_id"]),
                        "title": block["title"],
                        "priority": block["priority"],
                        "estimated_minutes": block["estimated_minutes"],
                        "is_estimate": block["is_estimate"],
                        "start_at_local": _local(block["start_at"], self.timezone),
                        "end_at_local": _local(block["end_at"], self.timezone),
                        "reasons": block["reasons"],
                    }
                    for block in blocks
                ]
                total = sum(int(block["estimated_minutes"]) for block in blocks)
                return _json(
                    {
                        "ok": True,
                        "kind": "planning_context",
                        "plan_date": target_date.isoformat(),
                        "available_minutes": available_minutes,
                        "planned_minutes": total,
                        "remaining_minutes": available_minutes - total,
                        "existing_plan": (
                            {
                                "available_minutes": existing.available_minutes,
                                "items": [
                                    {
                                        "task_id": str(item.task_id),
                                        "title": item.task_title,
                                        "start_at_local": _local(item.start_at, self.timezone),
                                        "end_at_local": _local(item.end_at, self.timezone),
                                    }
                                    for item in existing.items
                                ],
                            }
                            if existing
                            else None
                        ),
                        "blocks": payload,
                        "message": (
                            f"已生成 {target_date.isoformat()} 的 {len(payload)} 个候选时间块，"
                            f"共 {total} 分钟；其中未填写预计耗时的任务按 30 分钟估算。"
                        ),
                    }
                )
            except Exception as exc:
                logger.exception("get_planning_context failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取今日计划数据失败，请稍后重试。",
                    }
                )

        @tool
        def get_activity_log(
            period: Literal["today", "week", "all"] = "today",
            project_id: str | None = None,
        ) -> str:
            """Read real activity records (task/project changes) for a review or
            report. Never invent activity history."""
            try:
                now = utc_now()
                local_now = now.astimezone(self.timezone)
                day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                if period == "today":
                    since = day_start.astimezone(UTC)
                elif period == "week":
                    week_start = day_start - timedelta(days=day_start.weekday())
                    since = week_start.astimezone(UTC)
                else:
                    since = None
                parsed_project = _uuid_or_none(project_id, "project_id")
                activities = self.activity_service.list_activities(
                    project_id=parsed_project,
                    since=since,
                    limit=100,
                )
                return _json(
                    {
                        "ok": True,
                        "kind": "activities",
                        "period": period,
                        "count": len(activities),
                        "activities": [
                            {
                                "action": item.action,
                                "summary": item.summary,
                                "task_title": item.task_title,
                                "project_name": item.project_name,
                                "created_at_local": _local(item.created_at, self.timezone),
                            }
                            for item in activities
                        ],
                        "message": f"读取到 {len(activities)} 条真实活动记录。",
                    }
                )
            except Exception as exc:
                logger.exception("get_activity_log failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取活动记录失败，请稍后重试。",
                    }
                )

        @tool
        def get_report_facts(
            report_type: Literal["daily", "weekly", "project"],
            period_start: str | None = None,
            period_end: str | None = None,
            project_id: str | None = None,
        ) -> str:
            """Read backend-computed statistics for a report. All counts and task
            lists are real; completed work is scoped by completed_at. Use these
            facts to answer questions about a report. This never saves a report."""
            try:
                request = self._report_request(report_type, period_start, period_end, project_id)
                draft = self.report_service.generate(request, use_ai=False)
                facts = draft.facts
                counts = facts.get("counts", {})
                return _json(
                    {
                        "ok": True,
                        "kind": "report_facts",
                        "report_type": report_type,
                        "title": draft.title,
                        "period_start_local": facts.get("period_start_local"),
                        "period_end_local": facts.get("period_end_local"),
                        "counts": counts,
                        "completed_tasks": [
                            item.get("title")
                            for item in facts.get("completed_tasks", [])
                            if isinstance(item, dict)
                        ],
                        "overdue_tasks": [
                            item.get("title")
                            for item in facts.get("overdue_tasks", [])
                            if isinstance(item, dict)
                        ],
                        "projects": facts.get("projects", []),
                        "message": (
                            f"已计算报告事实统计：完成 {counts.get('completed', 0)} 项，"
                            f"逾期 {counts.get('overdue', 0)} 项。"
                        ),
                    }
                )
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("get_report_facts failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "读取报告数据失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_create_task(
            title: str,
            description: str | None = None,
            due_at: str | None = None,
            project_id: str | None = None,
            priority: Literal["high", "medium", "low"] | None = None,
            estimated_minutes: int | None = None,
        ) -> str:
            """Prepare a create-task draft for user confirmation. This never
            writes a task. due_at must be ISO 8601 with a timezone offset when
            a concrete deadline is known; omit it if the user gave no time.
            project_id must come from query_projects, never invented."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                parsed_due_at = _parse_due_at(due_at, self.timezone)
                data = TaskCreate(
                    title=title,
                    description=description,
                    due_at=parsed_due_at,
                    project_id=_uuid_or_none(project_id, "project_id"),
                    priority=TaskPriority(priority or "medium"),
                    estimated_minutes=estimated_minutes,
                )
                action = self.action_service.create_task_draft(data)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "create_draft",
                        "action": view.model_dump(mode="json"),
                        "message": f"已生成待确认操作：{action.summary}。请用户确认后执行。",
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"任务信息无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_create_task failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成任务草稿失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_create_tasks(tasks: list[CreateTaskInput]) -> str:
            """Prepare up to five independent create-task drafts for one
            confirmation. This never writes tasks. Every task must have a
            grounded title from the user's request."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                if not 1 <= len(tasks) <= MAX_BATCH_CREATE:
                    return _json(
                        {
                            "ok": False,
                            "kind": "validation_error",
                            "message": f"一次需要 1-{MAX_BATCH_CREATE} 个任务草稿。",
                        }
                    )
                drafts = [
                    TaskCreate(
                        title=item.title,
                        description=item.description,
                        due_at=_parse_due_at(item.due_at, self.timezone),
                        project_id=_uuid_or_none(item.project_id, "project_id"),
                        priority=TaskPriority(item.priority or "medium"),
                        estimated_minutes=item.estimated_minutes,
                    )
                    for item in tasks
                ]
                action = self.action_service.create_tasks_drafts(
                    drafts,
                    summary=f"创建 {len(drafts)} 个任务草稿",
                )
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "create_tasks_draft",
                        "action": view.model_dump(mode="json"),
                        "message": (
                            f"已生成 {len(drafts)} 个任务草稿的待确认操作。请用户确认后执行。"
                        ),
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"任务草稿无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_create_tasks failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成批量任务草稿失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_task_breakdown(
            goal: str,
            tasks: list[BreakdownTaskInput],
            project_id: str | None = None,
        ) -> str:
            """Prepare an editable task breakdown for one confirmation. Use this
            when the user asks to break a complex goal into tasks. Each task may
            have subtasks (one extra level only). This never writes tasks; the
            returned warnings must be shown to the user. project_id must come
            from query_projects."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                if not 1 <= len(tasks) <= 12:
                    return _json(
                        {
                            "ok": False,
                            "kind": "validation_error",
                            "message": "任务拆解需要 1-12 个父任务。",
                        }
                    )
                parsed_project = _uuid_or_none(project_id, "project_id")
                draft, warnings = self._breakdown_draft(goal, parsed_project, tasks)
                action = self.action_service.create_breakdown_draft(draft)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "breakdown_draft",
                        "action": view.model_dump(mode="json"),
                        "warnings": warnings,
                        "message": (
                            f"已生成任务拆解草稿：{action.summary}。"
                            "请用户在确认前检查、编辑或删除条目。"
                        ),
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"任务拆解内容无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_task_breakdown failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成任务拆解草稿失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_save_daily_plan(
            plan_date: str,
            available_minutes: int,
            items: list[PlanDraftItem],
        ) -> str:
            """Prepare a daily plan for user confirmation. Use real task IDs from
            get_planning_context/query_tasks and their suggested blocks. Never
            schedule completed tasks, invented tasks, overlapping blocks, or
            more minutes than available_minutes. This never saves the plan."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                target_date = _parse_plan_date(plan_date, self.timezone)
                plan = PlanDraft(
                    plan_date=target_date,
                    available_minutes=available_minutes,
                    items=items,
                )
                self.planning_service.validate(
                    plan.plan_date,
                    [
                        PlanItemInput(
                            task_id=item.task_id,
                            start_at=item.start_at,
                            end_at=item.end_at,
                            note=item.note,
                        )
                        for item in plan.items
                    ],
                    plan.available_minutes,
                )
                action = self.action_service.create_daily_plan_draft(plan)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "daily_plan_draft",
                        "action": view.model_dump(mode="json"),
                        "message": (
                            f"已生成 {target_date.isoformat()} 的今日计划草稿，请用户确认后保存。"
                        ),
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"今日计划无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except PlanConflictError as exc:
                return _json({"ok": False, "kind": "conflict", "message": exc.message})
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_save_daily_plan failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成今日计划草稿失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_save_report(
            report_type: Literal["daily", "weekly", "project"],
            period_start: str | None = None,
            period_end: str | None = None,
            project_id: str | None = None,
        ) -> str:
            """Generate a report from real backend statistics and prepare it for
            saving. The statistics and factual sections are computed by the
            backend; AI may only word the qualitative sections. This never saves
            the report before confirmation. Project reports require project_id."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                request = self._report_request(report_type, period_start, period_end, project_id)
                draft = self.report_service.generate(request, use_ai=True)
                action = self.action_service.create_report_draft(draft)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "report_draft",
                        "action": view.model_dump(mode="json"),
                        "ai_used": draft.ai_used,
                        "message": (
                            f"已生成报告草稿「{draft.title}」，统计范围 "
                            f"{draft.facts.get('period_start_local', '')} 至 "
                            f"{draft.facts.get('period_end_local', '')}。请用户确认后保存。"
                        ),
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"报告参数无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_save_report failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成报告草稿失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_complete_task(query: str) -> str:
            """Find tasks by title and prepare a completion action for user
            confirmation. This never changes a task. If multiple tasks match,
            the result contains candidates and the user must choose one. Do not
            retry with a candidate title in the same turn."""
            if state["ambiguity_blocked"]:
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "存在多个匹配任务，必须等用户明确选择后再操作。",
                    }
                )
            blocked = already_busy()
            if blocked:
                return blocked
            if not query.strip():
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "请提供要完成的任务标题。",
                    }
                )
            try:
                matches = self.task_service.search_tasks(query)
                if not matches:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": f"没有找到标题包含「{query.strip()}」的任务。",
                        }
                    )

                pending_matches = [
                    task for task in matches if task.status == TaskStatus.pending.value
                ]
                if not pending_matches:
                    return _json(
                        {
                            "ok": True,
                            "kind": "no_pending",
                            "message": "匹配到的任务都已经是已完成状态，无需再次标记。",
                        }
                    )

                selected, ambiguous = _select_unique(pending_matches, query)
                if selected is None:
                    state["ambiguity_blocked"] = True
                    candidates = [self._candidate(task) for task in ambiguous]
                    return _json(
                        {
                            "ok": True,
                            "kind": "ambiguous",
                            "candidates": candidates,
                            "message": f"找到 {len(candidates)} 个匹配任务，请明确选择要完成的任务。",
                        }
                    )

                action = self.action_service.create_completion_draft(selected)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "complete_draft",
                        "action": view.model_dump(mode="json"),
                        "message": f"已生成待确认操作：{action.summary}。请用户确认后执行。",
                    }
                )
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_complete_task failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成完成操作失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_update_task(
            query: str,
            new_title: str | None = None,
            new_description: str | None = None,
            new_due_at: str | None = None,
            new_priority: Literal["high", "medium", "low"] | None = None,
            new_estimated_minutes: int | None = None,
            new_project_id: str | None = None,
            clear_description: bool = False,
            clear_due_at: bool = False,
            clear_estimated_minutes: bool = False,
            clear_project: bool = False,
        ) -> str:
            """Prepare an edit action for one uniquely matched task. This never
            changes the task. Provide the new_* values, or the clear_* flags to
            remove a value. If multiple tasks match, ask for a more precise
            title; do not choose one yourself."""
            blocked = already_busy()
            if blocked:
                return blocked
            if not query.strip():
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "请提供要修改的任务标题。",
                    }
                )
            if clear_description and new_description is not None:
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "不能同时设置和清空描述。",
                    }
                )
            if clear_due_at and new_due_at is not None:
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "不能同时设置和清空截止时间。",
                    }
                )
            if clear_estimated_minutes and new_estimated_minutes is not None:
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "不能同时设置和清空预计耗时。",
                    }
                )
            if clear_project and new_project_id is not None:
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "不能同时设置和移出项目。",
                    }
                )
            try:
                changes: dict[str, object] = {}
                if new_title is not None:
                    changes["title"] = new_title
                if clear_description:
                    changes["description"] = None
                elif new_description is not None:
                    changes["description"] = new_description
                if clear_due_at:
                    changes["due_at"] = None
                elif new_due_at is not None:
                    changes["due_at"] = _parse_due_at(new_due_at, self.timezone)
                if new_priority is not None:
                    changes["priority"] = TaskPriority(new_priority)
                if clear_estimated_minutes:
                    changes["estimated_minutes"] = None
                elif new_estimated_minutes is not None:
                    changes["estimated_minutes"] = new_estimated_minutes
                if clear_project:
                    changes["project_id"] = None
                elif new_project_id is not None:
                    changes["project_id"] = _uuid_or_none(new_project_id, "project_id")
                if not changes:
                    return _json(
                        {
                            "ok": False,
                            "kind": "validation_error",
                            "message": "请至少提供一个要修改的字段。",
                        }
                    )
                parsed_changes = TaskChanges.model_validate(changes)
                matches = self.task_service.search_tasks(query)
                if not matches:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": f"没有找到标题包含「{query.strip()}」的任务。",
                        }
                    )
                selected, ambiguous = _select_unique(matches, query)
                if selected is None:
                    return ambiguous_result(
                        ambiguous,
                        action_label="修改任务",
                        query=query,
                    )

                summary = self._change_summary(selected, parsed_changes)
                action = self.action_service.create_update_draft(
                    selected,
                    parsed_changes,
                    summary=summary,
                )
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "update_draft",
                        "action": view.model_dump(mode="json"),
                        "message": f"已生成待确认操作：{summary}。请用户确认后执行。",
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"修改内容无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_update_task failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成修改操作失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_delete_task(query: str) -> str:
            """Prepare a delete action for one uniquely matched task. This never
            deletes anything. Deleting a parent also deletes its subtasks and
            the confirmation card says so. If multiple tasks match, ask the user
            for a more precise title; do not choose one yourself."""
            blocked = already_busy()
            if blocked:
                return blocked
            if not query.strip():
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "请提供要删除的任务标题。",
                    }
                )
            try:
                matches = self.task_service.search_tasks(query)
                if not matches:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": f"没有找到标题包含「{query.strip()}」的任务。",
                        }
                    )
                selected, ambiguous = _select_unique(matches, query)
                if selected is None:
                    return ambiguous_result(
                        ambiguous,
                        action_label="删除任务",
                        query=query,
                    )
                action = self.action_service.create_delete_draft(selected)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "delete_draft",
                        "action": view.model_dump(mode="json"),
                        "message": f"已生成待确认操作：{action.summary}。请用户确认后执行。",
                    }
                )
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_delete_task failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成删除操作失败，请稍后重试。",
                    }
                )

        @tool
        def prepare_batch_reschedule(
            scope: Literal["overdue", "due_today", "due_this_week", "all_pending"],
            new_due_at: str,
            search: str | None = None,
        ) -> str:
            """Prepare one bulk due-date change for pending tasks. scope picks a
            real task range (overdue, due today, due this week, all pending),
            search optionally narrows by title. This never changes tasks, caps
            the batch at 20, and always requires confirmation."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                due_at = _parse_due_at(new_due_at, self.timezone)
                if due_at is None:
                    return _json(
                        {
                            "ok": False,
                            "kind": "validation_error",
                            "message": "请提供新的截止时间。",
                        }
                    )
                now = utc_now()
                local_today = now.astimezone(self.timezone).date()
                week_start = local_today - timedelta(days=local_today.weekday())
                week_end = week_start + timedelta(days=7)
                pending = self.task_service.list_tasks(status=TaskStatus.pending)

                def matches_scope(task: Task) -> bool:
                    if search and search.strip():
                        if search.strip().casefold() not in task.title.casefold():
                            return False
                    if scope == "all_pending":
                        return True
                    if task.due_at is None:
                        return False
                    due_local = task.due_at.astimezone(self.timezone)
                    if scope == "overdue":
                        return task.due_at < now
                    if scope == "due_today":
                        return due_local.date() == local_today
                    return week_start <= due_local.date() < week_end

                matched = [task for task in pending if matches_scope(task)]
                if not matched:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": "当前范围内没有待完成的任务。",
                        }
                    )
                if len(matched) > MAX_BATCH_RESCHEDULE:
                    return _json(
                        {
                            "ok": False,
                            "kind": "validation_error",
                            "message": (
                                f"匹配到 {len(matched)} 个任务，超过单次 {MAX_BATCH_RESCHEDULE} "
                                "个上限，请缩小范围。"
                            ),
                        }
                    )
                summary = (
                    f"将 {len(matched)} 个任务的截止时间调整为 "
                    f"{_local_format(due_at, self.timezone)}"
                )
                action = self.action_service.create_batch_reschedule_draft(
                    matched,
                    due_at,
                    summary=summary,
                )
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "batch_reschedule_draft",
                        "action": view.model_dump(mode="json"),
                        "message": f"已生成待确认操作：{summary}。请用户确认后执行。",
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"批量改期信息无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except AppError as exc:
                return _json({"ok": False, "kind": "error", "message": exc.message})
            except Exception as exc:
                logger.exception("prepare_batch_reschedule failed: %s", type(exc).__name__)
                return _json(
                    {
                        "ok": False,
                        "kind": "error",
                        "message": "生成批量改期操作失败，请稍后重试。",
                    }
                )

        @tool
        def query_task_dependencies(
            task_id: str | None = None,
            query: str | None = None,
        ) -> str:
            """Read the prerequisites and dependents of one task. Returns whether
            the task is currently blocked and which tasks block it. Use it before
            suggesting an execution order or completing a task."""
            try:
                target: Task | None = None
                if task_id and task_id.strip():
                    target = self.task_service.get_task_or_none(task_id.strip())
                elif query and query.strip():
                    matches = self.task_service.search_tasks(query.strip())
                    if len(matches) == 1:
                        target = matches[0]
                    elif len(matches) > 1:
                        return _json(
                            {
                                "ok": True,
                                "kind": "needs_disambiguation",
                                "matches": [self._candidate(task) for task in matches],
                                "message": "找到多个匹配任务，请让用户补充更精确的标题。",
                            }
                        )
                if target is None:
                    return _json(
                        {
                            "ok": True,
                            "kind": "not_found",
                            "message": "没有找到这个任务，请先确认标题。",
                        }
                    )
                view = self.dependency_service.for_task(str(target.id))
                return _json(
                    {
                        "ok": True,
                        "kind": "dependencies",
                        "task": self._task_summary(target),
                        "is_blocked": view["is_blocked"],
                        "depends_on": view["depends_on"],
                        "blocks": view["blocks"],
                        "message": (
                            f"「{target.title}」"
                            + (
                                "当前被前置任务阻塞。"
                                if view["is_blocked"]
                                else "当前没有未完成的前置任务。"
                            )
                        ),
                    }
                )
            except Exception as exc:
                logger.warning("query_task_dependencies failed: %s", type(exc).__name__)
                return _json({"ok": False, "kind": "error", "message": "读取任务依赖失败。"})

        @tool
        def query_focus_stats() -> str:
            """Read real focus time: today, this week, per-day minutes, and the most
            focused tasks. Use it when the user asks how much they actually worked
            or wants a plan based on real execution time."""
            try:
                stats = self.focus_service.stats()
                payload = stats.model_dump(mode="json")
                return _json(
                    {
                        "ok": True,
                        "kind": "focus_stats",
                        "today": payload["today"],
                        "today_minutes": payload["today_seconds"] // 60,
                        "week_minutes": payload["week_seconds"] // 60,
                        "sessions": payload["session_count"],
                        "by_day": payload["by_day"],
                        "by_task": payload["by_task"],
                        "message": (
                            f"今天专注 {payload['today_seconds'] // 60} 分钟，"
                            f"本周 {payload['week_seconds'] // 60} 分钟。"
                        ),
                    }
                )
            except Exception as exc:
                logger.warning("query_focus_stats failed: %s", type(exc).__name__)
                return _json({"ok": False, "kind": "error", "message": "读取专注统计失败。"})

        @tool
        def analyze_task_risks() -> str:
            """Run the rule-based risk analysis: overdue, due soon, blocked,
            stale, workload over capacity, project deadline risk and plan drift.
            Every item includes the reason and a suggested action."""
            try:
                result = self.insight_service.compute()
                items = [item.model_dump(mode="json") for item in result.items]
                return _json(
                    {
                        "ok": True,
                        "kind": "risks",
                        "generated_at": result.generated_at.isoformat(),
                        "count": len(items),
                        "items": items,
                        "message": (
                            f"识别到 {len(items)} 条需要留意的风险。"
                            if items
                            else "目前没有识别到需要特别留意的风险。"
                        ),
                    }
                )
            except Exception as exc:
                logger.warning("analyze_task_risks failed: %s", type(exc).__name__)
                return _json({"ok": False, "kind": "error", "message": "风险分析失败。"})

        @tool
        def prepare_replan(
            plan_date: str | None = None,
            reason: str = "",
            available_minutes: int | None = None,
            unavailable_windows: list[dict[str, str]] | None = None,
        ) -> str:
            """Build a deterministic replan for one day and prepare it for user
            confirmation. Use it when the day did not go as planned, a meeting was
            inserted, or the user asks what to do next. The backend filters blocked
            tasks, respects capacity and occupied windows, and returns the changes.
            This never writes the plan before the user confirms."""
            blocked = already_busy()
            if blocked:
                return blocked
            try:
                target_date = _parse_plan_date(plan_date, self.timezone)
                draft = self.replan_service.preview(
                    plan_date=target_date,
                    reason=reason,
                    available_minutes=available_minutes,
                    unavailable_windows=unavailable_windows or [],
                )
                if not draft.after:
                    return _json(
                        {
                            "ok": True,
                            "kind": "empty_plan",
                            "plan_date": draft.plan_date.isoformat(),
                            "explanation": draft.explanation,
                            "blocked_tasks": len(draft.blocked_tasks),
                            "message": "这一天没有可以继续安排的任务，未生成待确认方案。",
                        }
                    )
                action = self.action_service.create_replan_draft(draft)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "replan_draft",
                        "action": view.model_dump(mode="json"),
                        "plan_date": draft.plan_date.isoformat(),
                        "changes": [change.model_dump(mode="json") for change in draft.changes],
                        "blocked_tasks": len(draft.blocked_tasks),
                        "unscheduled": len(draft.unscheduled),
                        "explanation": draft.explanation,
                        "message": "已生成重排方案，请用户确认后才会写入计划。",
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"重排参数无效：{first.get('msg', '请检查日期')}",
                    }
                )
            except Exception as exc:
                logger.warning("prepare_replan failed: %s", type(exc).__name__)
                return _json(
                    {"ok": False, "kind": "error", "message": "生成重排方案失败，请重试。"}
                )

        @tool
        def prepare_create_project(
            name: str,
            description: str | None = None,
            status: Literal["planning", "active", "completed", "archived"] = "planning",
            start_date: str | None = None,
            due_date: str | None = None,
        ) -> str:
            """Prepare a work project for user confirmation. Use it when the user
            starts a new work stream (for example a company project) before adding
            tasks or asking for a work daily report. This never creates the
            project before the user confirms."""
            blocked = already_busy()
            if blocked:
                return blocked
            if not name or not name.strip():
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": "请提供项目名称。",
                    }
                )
            try:
                from app.schemas import ProjectCreate, ProjectStatus

                def parse_day(value: str | None, label: str):
                    if value is None or not str(value).strip():
                        return None
                    try:
                        return date.fromisoformat(str(value).strip())
                    except ValueError as exc:
                        raise ValueError(f"{label} 需要 YYYY-MM-DD 格式") from exc

                data = ProjectCreate(
                    name=name.strip(),
                    description=description,
                    status=ProjectStatus(status),
                    start_date=parse_day(start_date, "start_date"),
                    due_date=parse_day(due_date, "due_date"),
                )
                action = self.action_service.create_project_draft(data)
                view = self.action_service.to_view(action)
                state["draft_created"] = True
                return _json(
                    {
                        "ok": True,
                        "kind": "project_draft",
                        "action": view.model_dump(mode="json"),
                        "message": "已生成项目草稿，请用户确认后创建。",
                    }
                )
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                return _json(
                    {
                        "ok": False,
                        "kind": "validation_error",
                        "message": f"项目信息无效：{first.get('msg', '请检查输入')}",
                    }
                )
            except ValueError as exc:
                return _json({"ok": False, "kind": "validation_error", "message": str(exc)})
            except Exception as exc:
                logger.warning("prepare_create_project failed: %s", type(exc).__name__)
                return _json(
                    {"ok": False, "kind": "error", "message": "创建项目草稿失败，请重试。"}
                )

        return [
            query_tasks,
            query_projects,
            query_task_dependencies,
            query_focus_stats,
            analyze_task_risks,
            prepare_replan,
            prepare_create_project,
            get_task_subtasks,
            get_agenda,
            get_priority_suggestions,
            get_planning_context,
            get_activity_log,
            get_report_facts,
            prepare_create_task,
            prepare_create_tasks,
            prepare_task_breakdown,
            prepare_save_daily_plan,
            prepare_save_report,
            prepare_complete_task,
            prepare_update_task,
            prepare_delete_task,
            prepare_batch_reschedule,
        ]

    def _report_request(
        self,
        report_type: str,
        period_start: str | None,
        period_end: str | None,
        project_id: str | None,
    ) -> ReportGenerateRequest:
        def day_start(day: date) -> datetime:
            return datetime.combine(day, datetime.min.time(), tzinfo=self.timezone)

        def parse(value: str | None, label: str, *, is_end: bool) -> datetime | None:
            if value is None or not value.strip():
                return None
            raw = value.strip().replace("Z", "+00:00")
            date_only = len(raw) == 10 and raw[4] == "-" and raw[7] == "-"
            try:
                if date_only:
                    day = date.fromisoformat(raw)
                    parsed = day_start(day + timedelta(days=1)) if is_end else day_start(day)
                else:
                    parsed = datetime.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(f"{label} 必须是 ISO 8601 日期时间或日期") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=self.timezone)
            return parsed

        start = parse(period_start, "period_start", is_end=False)
        end = parse(period_end, "period_end", is_end=True)

        # Models sometimes send only one side, or a same-day date range. Turn
        # that into one explicit local day instead of failing the whole tool.
        if start is None and end is not None:
            local_end = end.astimezone(self.timezone)
            start = day_start(local_end.date())
            if start >= end:
                start = day_start(local_end.date() - timedelta(days=1))
        if start is not None and end is None:
            local_start = start.astimezone(self.timezone)
            end = day_start(local_start.date() + timedelta(days=1))
        if start is not None and end is not None and end <= start:
            local_start = start.astimezone(self.timezone)
            local_end = end.astimezone(self.timezone)
            if local_start.date() == local_end.date():
                end = day_start(local_start.date() + timedelta(days=1))
            else:
                raise ValueError("period_end 必须晚于 period_start")

        return ReportGenerateRequest(
            report_type=ReportType(report_type),
            period_start=start,
            period_end=end,
            project_id=(UUID(project_id) if project_id and project_id.strip() else None),
        )


def _select_unique(tasks: list[Task], query: str) -> tuple[Task | None, list[Task]]:
    normalized = query.strip().casefold()
    exact = [task for task in tasks if task.title.casefold() == normalized]
    if len(exact) == 1:
        return exact[0], []
    if len(tasks) == 1:
        return tasks[0], []
    return None, tasks
