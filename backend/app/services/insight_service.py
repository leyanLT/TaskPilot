"""Rule-based task risk insights.

Every insight is derived from stored facts (due dates, dependencies, focus
records, plan items, project dates). Nothing here predicts the future or invents
numbers; the output explains *why* the item was raised and links the tasks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utc_now
from app.models import Project, Task
from app.repositories.v2_repository import FocusRepository, PreferenceRepository
from app.schemas_v2 import InsightListRead, InsightRead
from app.services.dependency_service import DependencyService
from app.services.planning_service import PlanningService

DUE_SOON_HOURS = 24
STALE_DAYS = 7
WORKLOAD_HORIZON_DAYS = 7
PROJECT_RISK_DAYS = 14
PROJECT_RISK_COMPLETION = 60


class InsightService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.preferences = PreferenceRepository(session)
        self.focus = FocusRepository(session)
        self.dependencies = DependencyService(session)
        self.planning = PlanningService(session, timezone=timezone)

    # -- dismissal -------------------------------------------------------

    def _dismissed_today(self, today: date) -> set[str]:
        preference = self.preferences.get()
        if preference is None or not preference.dismissed_insights:
            return set()
        keys = set()
        for entry in preference.dismissed_insights:
            if isinstance(entry, dict) and entry.get("on") == today.isoformat():
                keys.add(str(entry.get("key")))
        return keys

    def dismiss(self, key: str) -> None:
        preference = self.preferences.get()
        today = utc_now().astimezone(self.timezone).date()
        if preference is None:
            from app.models import UserPreference

            preference = UserPreference(
                id="default",
                timezone=self.timezone.key,
                daily_available_minutes=300,
                default_focus_minutes=25,
            )
        existing = [
            entry
            for entry in (preference.dismissed_insights or [])
            if isinstance(entry, dict) and entry.get("on") == today.isoformat()
        ]
        existing.append({"key": key, "on": today.isoformat()})
        preference.dismissed_insights = existing
        self.preferences.save(preference)
        self.session.commit()

    # -- rules -----------------------------------------------------------

    def compute(self) -> InsightListRead:
        now = utc_now()
        today = now.astimezone(self.timezone).date()
        pending = list(
            self.session.scalars(select(Task).where(Task.status == "pending").order_by(Task.due_at))
        )
        dismissed = self._dismissed_today(today)
        preferences = self.preferences.get()
        daily_minutes = preferences.daily_available_minutes if preferences else 300
        workdays = (
            set(preferences.workdays) if preferences and preferences.workdays else {0, 1, 2, 3, 4}
        )
        focus_recent = {
            row.task_id
            for row in self.focus.started_between(now - timedelta(days=STALE_DAYS), now)
            if row.status in ("running", "paused", "completed")
        }

        items: list[InsightRead] = []
        overdue = [task for task in pending if task.due_at and task.due_at < now]
        if overdue:
            items.append(
                InsightRead(
                    key="overdue",
                    code="TASK_OVERDUE",
                    severity="high",
                    title=f"{len(overdue)} 个任务已经逾期",
                    reason="这些任务的截止时间已经过去，但仍未完成。",
                    suggestion="先挑最早截止的一个开始专注，或统一改期到现实可完成的日期。",
                    task_ids=[UUID(task.id) for task in overdue[:8]],
                    task_titles=[task.title for task in overdue[:8]],
                    metric={"count": len(overdue)},
                )
            )

        soon = [
            task
            for task in pending
            if task.due_at and now <= task.due_at <= now + timedelta(hours=DUE_SOON_HOURS)
        ]
        if soon:
            items.append(
                InsightRead(
                    key="due_soon",
                    code="TASK_DUE_SOON",
                    severity="medium",
                    title=f"{len(soon)} 个任务将在 {DUE_SOON_HOURS} 小时内截止",
                    reason="按当前剩余时间，这些任务需要尽快安排。",
                    suggestion="把它们排进今天的日历时间块，或用「重排今天」让系统重新分配。",
                    task_ids=[UUID(task.id) for task in soon],
                    task_titles=[task.title for task in soon],
                    metric={"count": len(soon)},
                )
            )

        blocked_rows = self.dependencies.blocked_titles([task.id for task in pending])
        if blocked_rows:
            titles = [task.title for task in pending if task.id in blocked_rows]
            items.append(
                InsightRead(
                    key="blocked",
                    code="TASK_BLOCKED",
                    severity="medium",
                    title=f"{len(blocked_rows)} 个任务被前置任务挡住",
                    reason="前置任务没有完成之前，这些任务无法推进。",
                    suggestion="优先完成前置任务，或到任务详情里调整依赖关系。",
                    task_ids=[UUID(task.id) for task in pending if task.id in blocked_rows][:8],
                    task_titles=titles[:8],
                    metric={
                        "count": len(blocked_rows),
                        "pairs": {
                            task_id: names for task_id, names in list(blocked_rows.items())[:8]
                        },
                    },
                )
            )

        stale = [
            task
            for task in pending
            if task.updated_at < now - timedelta(days=STALE_DAYS) and task.id not in focus_recent
        ]
        if stale:
            items.append(
                InsightRead(
                    key="stale",
                    code="TASK_STALE",
                    severity="low",
                    title=f"{len(stale)} 个任务 {STALE_DAYS} 天没有进展",
                    reason="既没有修改记录，也没有专注记录；可能是被忘掉了。",
                    suggestion="确认还要不要做：继续就安排时间，不做就删掉或改期。",
                    task_ids=[UUID(task.id) for task in stale[:8]],
                    task_titles=[task.title for task in stale[:8]],
                    metric={"count": len(stale)},
                )
            )

        capacity = self._capacity_minutes(today, daily_minutes, workdays)
        demand = sum(
            task.estimated_minutes or 30
            for task in pending
            if task.due_at is None or task.due_at <= now + timedelta(days=WORKLOAD_HORIZON_DAYS)
        )
        if capacity and demand > capacity:
            items.append(
                InsightRead(
                    key="workload",
                    code="WORKLOAD_OVER_CAPACITY",
                    severity="high",
                    title=f"未来 {WORKLOAD_HORIZON_DAYS} 天工作量超出可用时间",
                    reason=(
                        f"待办预计需要 {demand} 分钟，"
                        f"按每天 {daily_minutes} 分钟计算只剩 {capacity} 分钟。"
                    ),
                    suggestion="降低范围、延长截止时间，或把低优先级任务移出本周。",
                    metric={"demand_minutes": demand, "capacity_minutes": capacity},
                )
            )

        items.extend(self._project_risks(today))
        plan_insight = self._plan_drift(today, now)
        if plan_insight:
            items.append(plan_insight)

        visible = [item for item in items if item.key not in dismissed]
        order = {"high": 0, "medium": 1, "low": 2}
        visible.sort(key=lambda item: (order[item.severity], item.key))
        return InsightListRead(
            generated_at=now,
            items=visible,
            dismissed_count=len(items) - len(visible),
        )

    def _capacity_minutes(self, today: date, daily_minutes: int, workdays: set[int]) -> int:
        total = 0
        for offset in range(WORKLOAD_HORIZON_DAYS):
            day = today + timedelta(days=offset)
            if day.weekday() in workdays:
                total += daily_minutes
        return total

    def _project_risks(self, today: date) -> list[InsightRead]:
        projects = list(
            self.session.scalars(select(Project).where(Project.status.in_(("planning", "active"))))
        )
        risky: list[InsightRead] = []
        for project in projects:
            if project.due_date is None:
                continue
            days_left = (project.due_date - today).days
            if days_left < 0 or days_left > PROJECT_RISK_DAYS:
                continue
            from app.services.project_service import ProjectService

            stats = ProjectService(self.session, timezone=self.timezone).stats(project.id)
            if stats.completion_rate >= PROJECT_RISK_COMPLETION:
                continue
            risky.append(
                InsightRead(
                    key=f"project:{project.id}",
                    code="PROJECT_DEADLINE_RISK",
                    severity="high" if days_left <= 7 else "medium",
                    title=f"项目「{project.name}」还有 {days_left} 天截止，完成度 {stats.completion_rate}%",
                    reason="项目截止日期临近，但已完成任务比例仍然偏低。",
                    suggestion="检查剩余任务，砍掉不必要范围，或用 Agent 生成下一阶段计划。",
                    project_id=UUID(project.id),
                    metric={
                        "days_left": days_left,
                        "completion_rate": stats.completion_rate,
                        "pending_tasks": stats.pending_tasks,
                    },
                )
            )
        return risky

    def _plan_drift(self, today: date, now: datetime) -> InsightRead | None:
        try:
            plan = self.planning.get_plan_or_none(today)
        except Exception:  # pragma: no cover - defensive
            return None
        if plan is None or not plan.items:
            return None
        missed = [
            item for item in plan.items if item.end_at < now and item.task_status == "pending"
        ]
        if len(missed) < 2:
            return None
        return InsightRead(
            key="plan_drift",
            code="PLAN_DRIFT",
            severity="medium",
            title=f"今天的计划有 {len(missed)} 段时间已经过去但任务还没完成",
            reason="计划时间与实际执行出现偏差，后面的安排可能也需要顺延。",
            suggestion="用「重排今天」按剩余时间重新生成时间块，并保留仍然想做的任务。",
            task_ids=[item.task_id for item in missed[:8]],
            task_titles=[item.task_title for item in missed[:8]],
            metric={"missed_blocks": len(missed), "planned_blocks": len(plan.items)},
        )

    # -- helper used by the assistant tool -------------------------------

    @staticmethod
    def group_by_severity(items: list[InsightRead]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            counts[item.severity] += 1
        return dict(counts)
