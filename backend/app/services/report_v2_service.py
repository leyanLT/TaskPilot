"""Enhanced V2.0 reports: real work-time, plan comparison, trends and risks.

All numbers come from stored rows (tasks, focus sessions, plan items). The
optional model call only words the qualitative suggestion section; it never
produces statistics. Every facts block lists the tables it was derived from.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import InvalidDateRangeError, ProjectNotFoundError
from app.models import Project, Task
from app.repositories.plan_repository import PlanRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.v2_repository import FocusRepository
from app.schemas import ReportDraft, ReportType
from app.services.dependency_service import DependencyService
from app.services.focus_service import FocusService
from app.services.insight_service import InsightService
from app.services.project_service import ProjectService
from app.services.replan_service import ReplanService

MAX_REPORT_DAYS = 92


def focus_by_task_total(counter: Counter[str]) -> int:
    return sum(counter.values()) // 60


class ReportV2Service:
    def __init__(
        self,
        session: Session,
        *,
        timezone: ZoneInfo,
        narrative_writer: Callable[[str], str] | None = None,
    ) -> None:
        self.session = session
        self.timezone = timezone
        self.tasks = TaskRepository(session)
        self.plans = PlanRepository(session)
        self.focus = FocusRepository(session)
        self.focus_service = FocusService(session, timezone=timezone)
        self.projects = ProjectService(session, timezone=timezone)
        self.dependencies = DependencyService(session)
        self.narrative_writer = narrative_writer

    # -- helpers ---------------------------------------------------------

    def _bounds(self, start: date, end: date) -> tuple[datetime, datetime]:
        start_local = datetime.combine(start, time.min, tzinfo=self.timezone)
        end_local = datetime.combine(end + timedelta(days=1), time.min, tzinfo=self.timezone)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    def _local_date(self, moment: datetime) -> date:
        return moment.astimezone(self.timezone).date()

    @staticmethod
    def _bar(value: int, maximum: int, width: int = 10) -> str:
        if maximum <= 0:
            return ""
        filled = max(0, min(width, round(value / maximum * width)))
        return "█" * filled + "░" * (width - filled)

    # -- main ------------------------------------------------------------

    def generate(
        self,
        *,
        report_type: ReportType,
        period_start: date,
        period_end: date,
        project_id: str | None = None,
        template: str = "standard",
    ) -> ReportDraft:
        if period_end < period_start:
            raise InvalidDateRangeError("结束日期不能早于开始日期。")
        if (period_end - period_start).days + 1 > MAX_REPORT_DAYS:
            raise InvalidDateRangeError(f"报告时间范围最多 {MAX_REPORT_DAYS} 天。")
        project = None
        if project_id:
            project = self.session.get(Project, project_id)
            if project is None:
                raise ProjectNotFoundError()
        start_dt, end_dt = self._bounds(period_start, period_end)
        now = utc_now()

        completed = [
            task
            for task in self.tasks.completed_between(start_dt, end_dt)
            if not project_id or task.project_id == project_id
        ]
        created = [
            task
            for task in self.tasks.created_between(start_dt, end_dt)
            if not project_id or task.project_id == project_id
        ]
        pending_at_end = list(
            self.session.scalars(
                select(Task).where(
                    Task.created_at < end_dt,
                    (Task.completed_at.is_(None)) | (Task.completed_at >= end_dt),
                )
            )
        )
        pending_at_end = [
            task for task in pending_at_end if not project_id or task.project_id == project_id
        ]
        overdue_at_end = [
            task for task in pending_at_end if task.due_at is not None and task.due_at < end_dt
        ]
        blocked_map = self.dependencies.blocked_titles([task.id for task in pending_at_end])

        focus_rows = self.focus.started_between(start_dt, min(end_dt, now))
        focus_seconds = 0
        focus_by_day: Counter[date] = Counter()
        focus_by_task: Counter[str] = Counter()
        focus_titles: dict[str, str] = {}
        for row in focus_rows:
            seconds = (
                row.accumulated_seconds
                if row.status == "completed"
                else self.focus_service.elapsed_seconds(row, now)
            )
            if project_id:
                task = self.session.get(Task, row.task_id)
                if task is None or task.project_id != project_id:
                    continue
            focus_seconds += seconds
            focus_by_day[row.started_at.astimezone(self.timezone).date()] += seconds
            focus_by_task[row.task_id] += seconds
            if row.task_id not in focus_titles:
                task = self.session.get(Task, row.task_id)
                focus_titles[row.task_id] = task.title if task else "（任务已删除）"

        planned_minutes = 0
        planned_blocks = 0
        completed_blocks = 0
        completed_planned_minutes = 0
        day_cursor = period_start
        while day_cursor <= period_end:
            plan = self.plans.get_by_date(day_cursor)
            if plan is not None:
                for item in self.plans.items(plan.id):
                    task = self.session.get(Task, item.task_id)
                    if task is None or (project_id and task.project_id != project_id):
                        continue
                    duration = int((item.end_at - item.start_at).total_seconds() // 60)
                    planned_minutes += duration
                    planned_blocks += 1
                    if task.completed_at is not None and start_dt <= task.completed_at < end_dt:
                        completed_blocks += 1
                        completed_planned_minutes += duration
            day_cursor += timedelta(days=1)

        trend_days = (period_end - period_start).days + 1
        trend = []
        for offset in range(trend_days):
            day = period_start + timedelta(days=offset)
            trend.append(
                {
                    "date": day.isoformat(),
                    "completed": sum(
                        1
                        for task in completed
                        if task.completed_at and self._local_date(task.completed_at) == day
                    ),
                }
            )

        project_rows = []
        project_query = select(Project)
        projects = list(self.session.scalars(project_query))
        for candidate in projects:
            if project_id and candidate.id != project_id:
                continue
            stats = self.projects.stats(candidate.id)
            project_rows.append(
                {
                    "id": candidate.id,
                    "name": candidate.name,
                    "status": candidate.status,
                    "due_date": candidate.due_date.isoformat() if candidate.due_date else None,
                    "total_tasks": stats.total_tasks,
                    "completed_tasks": stats.completed_tasks,
                    "pending_tasks": stats.pending_tasks,
                    "overdue_tasks": stats.overdue_tasks,
                    "completion_rate": stats.completion_rate,
                }
            )

        facts: dict[str, object] = {
            "generated_at": now.isoformat(),
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
                "days": trend_days,
                "timezone": self.timezone.key,
            },
            "scope": {
                "type": report_type.value,
                "project_id": project.id if project else None,
                "project_name": project.name if project else None,
            },
            "totals": {
                "completed": len(completed),
                "created": len(created),
                "pending_at_end": len(pending_at_end),
                "overdue_at_end": len(overdue_at_end),
                "blocked": len(blocked_map),
            },
            "focus": {
                "seconds": focus_seconds,
                "minutes": focus_seconds // 60,
                "sessions": len(focus_rows),
                "by_day": [
                    {"date": day.isoformat(), "minutes": seconds // 60}
                    for day, seconds in sorted(focus_by_day.items())
                ],
            },
            "plan": {
                "planned_minutes": planned_minutes,
                "planned_blocks": planned_blocks,
                "completed_blocks": completed_blocks,
                "completed_planned_minutes": completed_planned_minutes,
                "completion_rate": round(completed_blocks / planned_blocks * 100, 1)
                if planned_blocks
                else 0.0,
            },
            "trend": trend,
            "completed_tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
                for task in completed[:20]
            ],
            "projects": project_rows,
            "blocked_tasks": [
                {"task_id": task_id, "blocked_by": titles}
                for task_id, titles in list(blocked_map.items())[:10]
            ],
            "overdue_tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                }
                for task in overdue_at_end[:10]
            ],
            "sources": [
                "tasks.completed_at / tasks.created_at",
                "focus_sessions",
                "daily_plans + plan_items",
                "task_dependencies",
                "projects.due_date",
            ],
        }
        suggestions, ai_used = self._suggestions(facts)
        facts["suggestions"] = suggestions
        facts["ai_used"] = ai_used
        facts["template"] = template
        if template == "work":
            work = self._work_facts(
                report_type=report_type,
                period_start=period_start,
                period_end=period_end,
                project=project,
                completed=completed,
                pending=pending_at_end,
                overdue=overdue_at_end,
                blocked=blocked_map,
                focus_by_task=focus_by_task,
                focus_titles=focus_titles,
                focus_by_day=focus_by_day,
                trend=trend,
                plan_completed=completed_blocks,
                plan_total=planned_blocks,
            )
            facts["work"] = work
            markdown = self._work_markdown(facts, work)
        else:
            markdown = self._markdown(facts, suggestions)
        title = self._title(report_type, period_start, period_end, project, work=template == "work")
        return ReportDraft(
            report_type=report_type,
            title=title,
            period_start=start_dt,
            period_end=end_dt,
            project_id=UUID(project.id) if project else None,
            project_name=project.name if project else None,
            content_md=markdown,
            facts=facts,
            ai_used=ai_used,
        )

    # -- narrative -------------------------------------------------------

    def _suggestions(self, facts: dict[str, object]) -> tuple[str, bool]:
        totals = facts["totals"]
        plan = facts["plan"]
        focus = facts["focus"]
        fallback = []
        if totals["overdue_at_end"]:
            fallback.append(f"先处理 {totals['overdue_at_end']} 个逾期任务：改期或拆小。")
        if totals["blocked"]:
            fallback.append(f"有 {totals['blocked']} 个任务被前置任务阻塞，优先推进前置任务。")
        if plan["planned_blocks"] and plan["completion_rate"] < 60:
            fallback.append("计划完成率偏低：减少每天安排的时间块数量，留出缓冲。")
        if focus["minutes"] == 0:
            fallback.append("这段时间没有专注记录，可以先用 25 分钟番茄钟开始一件小事。")
        if not fallback:
            fallback.append("节奏稳定，可以继续保持当前的计划密度。")
        suggestions = "\n".join(f"- {line}" for line in fallback)
        if self.narrative_writer is None:
            return suggestions, False
        prompt = (
            "以下是 TaskPilot 计算出的真实统计（JSON）。请只依据这些事实，"
            "给出下一阶段 2-4 条可执行建议，每条一行，以「- 」开头。\n"
            + str({"totals": totals, "plan": plan, "focus": focus, "trend": facts["trend"]})
        )
        try:
            text = self.narrative_writer(prompt).strip()
        except Exception:  # AI failures must never break a report
            return suggestions, False
        return (text or suggestions), bool(text)

    # -- markdown --------------------------------------------------------

    # -- ByteDance-style work report ------------------------------------

    WEEKDAYS_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    def _cn_date(self, value: date) -> str:
        return f"{value.isoformat()}（{self.WEEKDAYS_CN[value.weekday()]}）"

    def _local_stamp(self, value: datetime) -> str:
        return value.astimezone(self.timezone).strftime("%m-%d %H:%M")

    def _work_facts(
        self,
        *,
        report_type: ReportType,
        period_start: date,
        period_end: date,
        project: Project | None,
        completed: list[Task],
        pending: list[Task],
        overdue: list[Task],
        blocked: dict[str, list[str]],
        focus_by_task: Counter[str],
        focus_titles: dict[str, str],
        focus_by_day: Counter[date],
        trend: list[dict[str, object]],
        plan_completed: int,
        plan_total: int,
    ) -> dict[str, object]:
        project_id = project.id if project else None
        project_names: dict[str, str] = {}
        for task in [*completed, *pending]:
            if task.project_id and task.project_id not in project_names:
                owner = self.session.get(Project, task.project_id)
                project_names[task.project_id] = owner.name if owner else "未命名项目"

        planned_ids: set[str] = set()
        day_cursor = period_start
        while day_cursor <= period_end:
            plan = self.plans.get_by_date(day_cursor)
            if plan is not None:
                for item in self.plans.items(plan.id):
                    task = self.session.get(Task, item.task_id)
                    if task is not None and (not project_id or task.project_id == project_id):
                        planned_ids.add(task.id)
            day_cursor += timedelta(days=1)

        completed_rows = [
            {
                "title": task.title,
                "estimated_minutes": task.estimated_minutes,
                "focus_minutes": focus_by_task.get(task.id, 0) // 60,
                "project": project_names.get(task.project_id or "", None),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }
            for task in completed[:20]
        ]

        def sort_key(task: Task) -> tuple[bool, float]:
            return (
                task.due_at is None,
                task.due_at.timestamp() if task.due_at else float("inf"),
            )

        pending_rows = []
        for task in sorted(pending, key=sort_key)[:12]:
            reasons: list[str] = []
            if task.id in blocked:
                reasons.append(f"被前置任务阻塞（{'、'.join(blocked[task.id][:3])}）")
            if task.due_at is not None and task.due_at < utc_now():
                reasons.append(f"已逾期（截止 {self._local_stamp(task.due_at)}）")
            if task.id in planned_ids:
                reasons.append("已排进计划但尚未完成")
            if not reasons:
                reasons.append("尚未开始")
            pending_rows.append(
                {
                    "title": task.title,
                    "reasons": reasons,
                    "due": task.due_at.isoformat() if task.due_at else None,
                    "estimated_minutes": task.estimated_minutes,
                }
            )

        mode = "daily" if report_type is ReportType.daily else "weekly"
        next_blocks: list[dict[str, object]] = []
        if mode == "daily":
            tomorrow = period_end + timedelta(days=1)
            draft = ReplanService(self.session, timezone=self.timezone).preview(
                plan_date=tomorrow, reason="工作日报：生成明日计划"
            )
            for block in draft.after:
                task = self.session.get(Task, str(block.task_id))
                if project_id and (task is None or task.project_id != project_id):
                    continue
                next_blocks.append(
                    {
                        "start": block.start_at.isoformat(),
                        "end": block.end_at.isoformat(),
                        "title": block.title,
                        "priority": str(block.priority),
                        "date": tomorrow.isoformat(),
                    }
                )
        else:
            for task in sorted(pending, key=sort_key)[:8]:
                next_blocks.append(
                    {
                        "title": task.title,
                        "priority": task.priority,
                        "date": task.due_at.date().isoformat() if task.due_at else None,
                        "start": None,
                        "end": None,
                    }
                )

        risk_rows: list[dict[str, str]] = []
        insights = InsightService(self.session, timezone=self.timezone).compute()
        pending_ids = {task.id for task in pending}
        for item in insights.items:
            if project_id:
                related = item.project_id == project_id or any(
                    str(task_id) in pending_ids for task_id in item.task_ids
                )
                if not related:
                    continue
            risk_rows.append({"title": item.title, "suggestion": item.suggestion})
            if len(risk_rows) >= 4:
                break

        daily_rows = [
            {
                "date": row["date"],
                "completed": row["completed"],
                "focus_minutes": focus_by_day.get(date.fromisoformat(str(row["date"])), 0) // 60,
            }
            for row in trend
        ]

        return {
            "mode": mode,
            "label": "工作日报" if mode == "daily" else "工作周报",
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
                "start_label": self._cn_date(period_start),
                "end_label": self._cn_date(period_end),
                "timezone": self.timezone.key,
            },
            "completed": completed_rows,
            "pending": pending_rows,
            "next_blocks": next_blocks,
            "risks": risk_rows,
            "daily": daily_rows,
            "focus_minutes": focus_by_task_total(focus_by_task),
            "focus_sessions": len([1 for _ in focus_by_task]),
            "plan": {"completed": plan_completed, "total": plan_total},
        }

    def _work_markdown(self, facts: dict[str, object], work: dict[str, object]) -> str:
        lines: list[str] = []
        scope = facts["scope"]["project_name"] or "全部工作"
        label = work["label"]
        mode = work["mode"]
        lines.append(f"# {label}｜{scope}")
        lines.append("")
        if mode == "daily":
            lines.append(f"**日期**：{work['period']['start_label']}")
        else:
            lines.append(
                f"**周期**：{work['period']['start']} ~ {work['period']['end']}（{work['period']['timezone']}）"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

        lines.append("## 一、今日完成" if mode == "daily" else "## 一、本周完成")
        lines.append("")
        completed = work["completed"]
        if completed:
            for item in completed:
                bits = []
                if item["project"]:
                    bits.append(str(item["project"]))
                if item["estimated_minutes"]:
                    bits.append(f"预计 {item['estimated_minutes']} 分钟")
                if item["focus_minutes"]:
                    bits.append(f"专注 {item['focus_minutes']} 分钟")
                suffix = f"（{'，'.join(bits)}）" if bits else ""
                lines.append(f"- {item['title']}{suffix}")
        else:
            lines.append("- 本期没有标记完成的任务。")
        lines.append("")

        lines.append("## 二、未完成 / 进行中")
        lines.append("")
        pending = work["pending"]
        if pending:
            for item in pending:
                due = f"；截止 {str(item['due'])[:16].replace('T', ' ')}" if item["due"] else ""
                lines.append(f"- {item['title']}：{'；'.join(item['reasons'])}{due}")
        else:
            lines.append("- 没有未完成事项。")
        lines.append("")

        lines.append("## 三、明日计划" if mode == "daily" else "## 三、下周计划")
        lines.append("")
        next_blocks = work["next_blocks"]
        if next_blocks:
            for block in next_blocks:
                if block.get("start"):
                    start = datetime.fromisoformat(str(block["start"])).astimezone(self.timezone)
                    end = datetime.fromisoformat(str(block["end"])).astimezone(self.timezone)
                    lines.append(
                        f"- {start:%H:%M}–{end:%H:%M}　{block['title']}（{block['priority']} 优先级）"
                    )
                else:
                    due = f"，截止 {block['date']}" if block.get("date") else ""
                    lines.append(f"- {block['title']}（{block['priority']} 优先级{due}）")
        else:
            lines.append("- 暂无需要安排的事项。")
        lines.append("")

        lines.append("## 四、风险与需要协调")
        lines.append("")
        risks = work["risks"]
        if risks:
            for risk in risks:
                lines.append(f"- {risk['title']}；建议：{risk['suggestion']}")
        else:
            lines.append("- 暂无需要额外协调的风险。")
        lines.append("")

        if mode == "weekly":
            lines.append("## 五、每日数据")
            lines.append("")
            lines.append("| 日期 | 完成 | 专注分钟 |")
            lines.append("| --- | --- | --- |")
            for row in work["daily"]:
                lines.append(f"| {row['date']} | {row['completed']} | {row['focus_minutes']} |")
            lines.append("")
            summary_heading = "## 六、数据小结"
        else:
            summary_heading = "## 五、数据小结"
        lines.append(summary_heading)
        lines.append("")
        totals = facts["totals"]
        lines.append(
            f"- 完成任务 {totals['completed']} 个，新建 {totals['created']} 个，"
            f"期末待完成 {totals['pending_at_end']} 个，逾期 {totals['overdue_at_end']} 个。"
        )
        lines.append(
            f"- 专注 {work['focus_minutes']} 分钟；计划 {work['plan']['total']} 块，"
            f"完成 {work['plan']['completed']} 块。"
        )
        lines.append(
            "- 数据来源：tasks.completed_at、focus_sessions、plan_items、task_dependencies、insights。"
        )
        lines.append("")
        lines.append(
            "说明：以上数据由后端按真实记录统计，未完成原因只列出可验证的客观事实；"
            "AI 仅参与措辞建议，不修改任何统计数字。"
        )
        return "\n".join(lines)

    def _title(
        self,
        report_type: ReportType,
        period_start: date,
        period_end: date,
        project: Project | None,
        *,
        work: bool = False,
    ) -> str:
        if work:
            label = {
                ReportType.daily: "工作日报",
                ReportType.weekly: "工作周报",
                ReportType.project: "项目工作汇报",
            }.get(report_type, "工作汇报")
        else:
            label = {
                ReportType.daily: "日报",
                ReportType.weekly: "周报",
                ReportType.project: "项目报告",
            }.get(report_type, "工作报告")
        scope = f" · {project.name}" if project else ""
        return f"TaskPilot {label}{scope}（{period_start.isoformat()} ~ {period_end.isoformat()}）"

    def _markdown(self, facts: dict[str, object], suggestions: str) -> str:
        totals = facts["totals"]
        focus = facts["focus"]
        plan = facts["plan"]
        period = facts["period"]
        lines: list[str] = []
        lines.append(f"# {facts['scope']['type']} · 工作统计")
        lines.append("")
        lines.append(
            f"统计范围：{period['start']} 至 {period['end']}（{period['days']} 天，"
            f"时区 {period['timezone']}）"
        )
        lines.append("")
        if facts["scope"]["project_name"]:
            lines.append(f"项目：{facts['scope']['project_name']}")
            lines.append("")
        lines.append("## 工作摘要")
        lines.append("")
        lines.append(
            f"本期完成 {totals['completed']} 个任务，新建 {totals['created']} 个，"
            f"期末仍有 {totals['pending_at_end']} 个待完成，其中逾期 {totals['overdue_at_end']} 个。"
        )
        lines.append("")
        lines.append("## 已完成事项")
        lines.append("")
        if facts["completed_tasks"]:
            for task in facts["completed_tasks"][:12]:
                lines.append(f"- {task['title']}")
        else:
            lines.append("- 本期没有已完成的任务。")
        lines.append("")
        lines.append("## 实际工作时间")
        lines.append("")
        lines.append(f"专注记录合计 {focus['minutes']} 分钟，来自 {focus['sessions']} 次专注会话。")
        if focus["by_day"]:
            lines.append("")
            lines.append("| 日期 | 专注分钟 |")
            lines.append("| --- | --- |")
            for row in focus["by_day"]:
                lines.append(f"| {row['date']} | {row['minutes']} |")
        lines.append("")
        lines.append("## 计划与实际")
        lines.append("")
        lines.append(
            f"安排了 {plan['planned_blocks']} 个时间块（{plan['planned_minutes']} 分钟），"
            f"其中 {plan['completed_blocks']} 个对应任务已完成，"
            f"占计划时间块 {plan['completion_rate']}%。"
        )
        lines.append("")
        lines.append("## 任务完成趋势")
        lines.append("")
        lines.append("| 日期 | 完成数 | 趋势 |")
        lines.append("| --- | --- | --- |")
        maximum = max((row["completed"] for row in facts["trend"]), default=0)
        for row in facts["trend"]:
            lines.append(
                f"| {row['date']} | {row['completed']} | {self._bar(row['completed'], maximum)} |"
            )
        lines.append("")
        lines.append("## 风险与阻塞")
        lines.append("")
        if facts["overdue_tasks"]:
            for task in facts["overdue_tasks"][:5]:
                lines.append(f"- 逾期：{task['title']}（截止 {task['due_at']}）")
        if facts["blocked_tasks"]:
            for row in facts["blocked_tasks"][:5]:
                titles = "、".join(row["blocked_by"])
                lines.append(f"- 阻塞任务 {row['task_id']}：等待 {titles}")
        if not facts["overdue_tasks"] and not facts["blocked_tasks"]:
            lines.append("- 没有记录到逾期或阻塞。")
        lines.append("")
        lines.append("## 项目进度")
        lines.append("")
        if facts["projects"]:
            lines.append("| 项目 | 完成率 | 待完成 | 截止 |")
            lines.append("| --- | --- | --- | --- |")
            for project in facts["projects"]:
                lines.append(
                    f"| {project['name']} | {project['completion_rate']}% | "
                    f"{project['pending_tasks']} | {project['due_date'] or '未设置'} |"
                )
        else:
            lines.append("- 没有项目数据。")
        lines.append("")
        lines.append("## 下一阶段建议")
        lines.append("")
        lines.append(suggestions)
        lines.append("")
        lines.append("## 数据来源")
        lines.append("")
        for source in facts["sources"]:
            lines.append(f"- {source}")
        lines.append("")
        lines.append(
            "说明：以上统计由后端根据真实记录计算；建议部分来自规则"
            + ("与模型润色" if facts.get("ai_used") else "")
            + "，不代表预测。"
        )
        return "\n".join(lines)
