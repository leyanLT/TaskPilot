"""Calendar view over the single source of truth: daily plans and plan items.

Time blocks are not duplicated in a second table. The calendar reads and writes
``daily_plans`` / ``plan_items`` through :class:`PlanningService`, so the daily
plan page and the calendar can never disagree.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.exceptions import (
    DatabaseOperationError,
    PlanConflictError,
    PlanNotFoundError,
    TaskNotFoundError,
    TimeBlockNotFoundError,
)
from app.models import DailyPlan, PlanItem, Task
from app.repositories.plan_repository import PlanRepository
from app.repositories.v2_repository import PreferenceRepository
from app.schemas import PlanItemInput, PlanUpsert
from app.schemas_v2 import (
    CalendarDayRead,
    CalendarRangeRead,
    CalendarTaskRead,
    TimeBlockCreate,
    TimeBlockRead,
    TimeBlockUpdate,
)
from app.services.dependency_service import DependencyService
from app.services.planning_service import PlanningService
from app.services.recurrence_service import RecurrenceService

DEFAULT_AVAILABLE_MINUTES = 300
MAX_RANGE_DAYS = 62


class CalendarService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.plans = PlanRepository(session)
        self.planning = PlanningService(session, timezone=timezone)
        self.preferences = PreferenceRepository(session)

    # -- helpers ---------------------------------------------------------

    def _available_minutes(self, plan: DailyPlan | None) -> int:
        if plan is not None:
            return plan.available_minutes
        preference = self.preferences.get()
        return preference.daily_available_minutes if preference else DEFAULT_AVAILABLE_MINUTES

    def _block_view(self, item: PlanItem, plan: DailyPlan, task: Task) -> TimeBlockRead:
        return TimeBlockRead(
            id=UUID(item.id),
            plan_id=UUID(plan.id),
            plan_date=plan.plan_date,
            task_id=UUID(task.id),
            task_title=task.title,
            task_status=task.status,
            start_at=item.start_at,
            end_at=item.end_at,
            note=item.note,
            position=item.position,
        )

    def _task_view(self, task: Task, blocked: dict[str, list[str]]) -> CalendarTaskRead:
        return CalendarTaskRead(
            id=UUID(task.id),
            title=task.title,
            status=task.status,
            priority=task.priority,
            due_at=task.due_at,
            project_id=UUID(task.project_id) if task.project_id else None,
            is_blocked=bool(blocked.get(task.id)),
            recurrence_rule_id=UUID(task.recurrence_rule_id) if task.recurrence_rule_id else None,
        )

    # -- reads -----------------------------------------------------------

    def range(
        self,
        start: date,
        end: date,
        *,
        project_id: str | None = None,
    ) -> CalendarRangeRead:
        if end < start:
            raise PlanConflictError("结束日期不能早于开始日期。")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise PlanConflictError(f"一次最多查看 {MAX_RANGE_DAYS} 天。")
        RecurrenceService(self.session, timezone=self.timezone).ensure_all()
        dependencies = DependencyService(self.session)
        day_count = (end - start).days + 1
        days: list[CalendarDayRead] = []
        total_planned = 0
        for offset in range(day_count):
            current = start + timedelta(days=offset)
            day_start, day_end = self.planning.local_day_bounds(current)
            plan = self.plans.get_by_date(current)
            items = self.plans.items(plan.id) if plan else []
            task_ids = {item.task_id for item in items}
            due_stmt = (
                select(Task)
                .where(Task.due_at.is_not(None), Task.due_at >= day_start, Task.due_at < day_end)
                .order_by(Task.due_at)
            )
            due_tasks = list(self.session.scalars(due_stmt))
            task_ids.update(task.id for task in due_tasks)
            blocked = dependencies.blocked_titles(list(task_ids))
            blocks: list[TimeBlockRead] = []
            for item in items:
                task = self.session.get(Task, item.task_id)
                if task is None:
                    continue
                if project_id and task.project_id != project_id:
                    continue
                blocks.append(self._block_view(item, plan, task))
            planned = int(
                sum((block.end_at - block.start_at).total_seconds() // 60 for block in blocks)
            )
            total_planned += planned
            filtered_due = [
                self._task_view(task, blocked)
                for task in due_tasks
                if not project_id or task.project_id == project_id
            ]
            days.append(
                CalendarDayRead(
                    date=current,
                    available_minutes=self._available_minutes(plan),
                    planned_minutes=planned,
                    blocks=blocks,
                    due_tasks=filtered_due,
                )
            )
        return CalendarRangeRead(
            start=start,
            end=end,
            days=days,
            total_planned_minutes=total_planned,
        )

    # -- time block writes ----------------------------------------------

    def _load_plan_items(self, plan: DailyPlan | None) -> list[PlanItemInput]:
        if plan is None:
            return []
        return [
            PlanItemInput(
                task_id=UUID(item.task_id),
                start_at=item.start_at,
                end_at=item.end_at,
                note=item.note,
            )
            for item in self.plans.items(plan.id)
        ]

    def _save(
        self,
        plan_date: date,
        items: list[PlanItemInput],
        available_minutes: int,
    ) -> None:
        try:
            self.planning.save_plan(
                plan_date,
                PlanUpsert(items=items, available_minutes=available_minutes),
            )
        except PlanNotFoundError:  # pragma: no cover - defensive
            raise

    def create_block(self, data: TimeBlockCreate) -> TimeBlockRead:
        task = self.session.get(Task, str(data.task_id))
        if task is None:
            raise TaskNotFoundError()
        if task.status == "completed":
            raise PlanConflictError(f"任务「{task.title}」已完成，不能安排时间块。")
        plan = self.plans.get_by_date(data.plan_date)
        available = self._available_minutes(plan)
        items = self._load_plan_items(plan)
        start_at = data.start_at.astimezone(UTC)
        end_at = data.end_at.astimezone(UTC)
        candidate = PlanItemInput(
            task_id=data.task_id,
            start_at=start_at,
            end_at=end_at,
            note=data.note,
        )
        self.planning.validate(data.plan_date, [*items, candidate], available)
        try:
            if plan is None:
                plan = DailyPlan(
                    plan_date=data.plan_date,
                    timezone=self.timezone.key,
                    available_minutes=available,
                )
                self.plans.add(plan)
            item = PlanItem(
                plan_id=plan.id,
                task_id=str(data.task_id),
                start_at=start_at,
                end_at=end_at,
                position=len(items),
                note=data.note,
            )
            self.plans.add_item(item)
            self._reindex(plan)
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        return self._block_view(item, plan, task)

    def update_block(self, block_id: str, data: TimeBlockUpdate) -> TimeBlockRead:
        item = self.session.get(PlanItem, block_id)
        if item is None:
            raise TimeBlockNotFoundError()
        plan = self.session.get(DailyPlan, item.plan_id)
        if plan is None:  # pragma: no cover - FK guarantees the plan
            raise TimeBlockNotFoundError()
        start_at = (data.start_at or item.start_at).astimezone(UTC)
        end_at = (data.end_at or item.end_at).astimezone(UTC)
        if end_at <= start_at:
            raise PlanConflictError("结束时间必须晚于开始时间。")
        task = self.session.get(Task, item.task_id)
        if task is None:  # pragma: no cover - FK cascade
            raise TaskNotFoundError()
        # Validate the replaced item together with its siblings before writing.
        candidate_items = []
        for existing in self._load_plan_items(plan):
            if str(existing.task_id) == item.task_id:
                candidate_items.append(
                    PlanItemInput(
                        task_id=existing.task_id,
                        start_at=start_at,
                        end_at=end_at,
                        note=data.note if data.note is not None else existing.note,
                    )
                )
            else:
                candidate_items.append(existing)
        self.planning.validate(plan.plan_date, candidate_items, plan.available_minutes)
        try:
            item.start_at = start_at
            item.end_at = end_at
            if data.note is not None:
                item.note = data.note
            self._reindex(plan)
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        return self._block_view(item, plan, task)

    def delete_block(self, block_id: str) -> None:
        item = self.session.get(PlanItem, block_id)
        if item is None:
            raise TimeBlockNotFoundError()
        plan = self.session.get(DailyPlan, item.plan_id)
        if plan is None:  # pragma: no cover
            raise TimeBlockNotFoundError()
        try:
            self.session.delete(item)
            self.session.flush()
            self._reindex(plan)
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    def _reindex(self, plan: DailyPlan) -> None:
        items = sorted(self.plans.items(plan.id), key=lambda row: row.start_at)
        for position, row in enumerate(items):
            row.position = position

    def day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self.timezone).astimezone(UTC)
        return start, (start + timedelta(days=1))
