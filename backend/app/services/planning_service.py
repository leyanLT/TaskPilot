"""Daily planning: validation, persistence, and deterministic scheduling.

The service never invents tasks and never schedules completed work. A plan is
stored as explicit UTC time blocks; the local plan date is derived from
``APP_TIMEZONE`` so the same database values render consistently everywhere.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    PlanConflictError,
    PlanNotFoundError,
    TaskNotFoundError,
)
from app.models import DailyPlan, PlanItem, Task
from app.repositories.plan_repository import PlanRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import (
    PlanItemInput,
    PlanItemRead,
    PlanRead,
    PlanUpsert,
    TaskPriority,
    TaskStatus,
)
from app.services.priority_service import PriorityAssessment, PriorityService

DEFAULT_ESTIMATE_MINUTES = 30
MAX_SUGGESTED_BLOCKS = 8


class PlanningService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.repository = PlanRepository(session)
        self.task_repository = TaskRepository(session)
        self.priority_service = PriorityService(session, timezone=timezone)

    def _rollback(self) -> None:
        try:
            self.session.rollback()
        except SQLAlchemyError:
            pass

    def _flush(self, *, commit: bool) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def local_day_bounds(self, plan_date: date) -> tuple[datetime, datetime]:
        start_local = datetime.combine(plan_date, time.min, tzinfo=self.timezone)
        return start_local.astimezone(UTC), (start_local + timedelta(days=1)).astimezone(UTC)

    def get_plan(self, plan_date: date) -> PlanRead:
        plan = self.repository.get_by_date(plan_date)
        if plan is None:
            raise PlanNotFoundError()
        items = self.repository.items(plan.id)
        tasks = self._load_tasks({item.task_id for item in items})
        views = [self._item_view(item, tasks.get(item.task_id)) for item in items]
        return PlanRead(
            id=UUID(plan.id),
            plan_date=plan.plan_date,
            timezone=plan.timezone,
            available_minutes=plan.available_minutes,
            planned_minutes=self._planned_minutes(items),
            items=views,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def get_plan_or_none(self, plan_date: date) -> PlanRead | None:
        try:
            return self.get_plan(plan_date)
        except PlanNotFoundError:
            return None

    @staticmethod
    def _planned_minutes(items: list[PlanItem]) -> int:
        return int(sum((item.end_at - item.start_at).total_seconds() // 60 for item in items))

    def _load_tasks(self, task_ids: set[str]) -> dict[str, Task]:
        if not task_ids:
            return {}
        tasks: dict[str, Task] = {}
        for task_id in task_ids:
            task = self.task_repository.get(task_id)
            if task is not None:
                tasks[task_id] = task
        return tasks

    @staticmethod
    def _item_view(item: PlanItem, task: Task | None) -> PlanItemRead:
        if task is None:
            # FK cascade removes items with deleted tasks; this is defensive only.
            raise PlanConflictError("计划中的任务已不存在，请重新安排。")
        return PlanItemRead(
            id=UUID(item.id),
            task_id=UUID(task.id),
            task_title=task.title,
            task_status=TaskStatus(task.status),
            priority=TaskPriority(task.priority),
            estimated_minutes=task.estimated_minutes,
            start_at=item.start_at,
            end_at=item.end_at,
            position=item.position,
            note=item.note,
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_plan(
        self,
        plan_date: date,
        data: PlanUpsert,
        *,
        commit: bool = True,
    ) -> PlanRead:
        normalized = self._validate(plan_date, data.items, data.available_minutes)
        existing = self.repository.get_by_date(plan_date)
        try:
            if existing is not None:
                self.repository.delete(existing)
                self.session.flush()
            plan = DailyPlan(
                plan_date=plan_date,
                timezone=self.timezone.key,
                available_minutes=data.available_minutes,
            )
            self.repository.add(plan)
            for index, item in enumerate(normalized):
                self.repository.add_item(
                    PlanItem(
                        plan_id=plan.id,
                        task_id=str(item.task_id),
                        start_at=item.start_at,
                        end_at=item.end_at,
                        position=index,
                        note=item.note,
                    )
                )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=commit)
        return self.get_plan(plan_date)

    def delete_plan(self, plan_date: date, *, commit: bool = True) -> None:
        plan = self.repository.get_by_date(plan_date)
        if plan is None:
            raise PlanNotFoundError()
        try:
            self.repository.delete(plan)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=commit)

    def _validate(
        self,
        plan_date: date,
        items: list[PlanItemInput],
        available_minutes: int,
    ) -> list[PlanItemInput]:
        seen: set[str] = set()
        for item in items:
            task_id = str(item.task_id)
            if task_id in seen:
                raise PlanConflictError("同一个任务不能在今日计划中出现两次。")
            seen.add(task_id)
            task = self.task_repository.get(task_id)
            if task is None:
                raise TaskNotFoundError()
            if task.status == TaskStatus.completed.value:
                raise PlanConflictError(f"任务「{task.title}」已完成，不能安排进今日计划。")
            local_start = item.start_at.astimezone(self.timezone)
            local_end = item.end_at.astimezone(self.timezone)
            if local_start.date() != plan_date or local_end.date() != plan_date:
                raise PlanConflictError("时间块必须落在计划当天的本地日期内。")
        total = int(sum((item.end_at - item.start_at).total_seconds() // 60 for item in items))
        if total > available_minutes:
            raise PlanConflictError(
                f"计划总时长 {total} 分钟超过可用时间 {available_minutes} 分钟。",
                details={"planned_minutes": total, "available_minutes": available_minutes},
            )
        ordered = sorted(items, key=lambda item: item.start_at)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.start_at < previous.end_at:
                raise PlanConflictError(
                    "时间块发生重叠，请调整开始或结束时间。",
                    details={
                        "first_start": previous.start_at.isoformat(),
                        "second_start": current.start_at.isoformat(),
                    },
                )
        return ordered

    def validate(
        self,
        plan_date: date,
        items: list[PlanItemInput],
        available_minutes: int,
    ) -> list[PlanItemInput]:
        """Public validation used before a plan draft is proposed to the user."""

        return self._validate(plan_date, items, available_minutes)

    # ------------------------------------------------------------------
    # Deterministic suggestion used by the UI and the agent tool
    # ------------------------------------------------------------------

    def suggest_blocks(
        self,
        plan_date: date,
        available_minutes: int,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, object]]:
        """Build a truthful, capacity-bounded proposal from real tasks."""

        now = now or utc_now()
        local_now = now.astimezone(self.timezone)
        if plan_date < local_now.date():
            return []
        day_start = datetime.combine(plan_date, time.min, tzinfo=self.timezone)
        if plan_date == local_now.date():
            start = max(
                local_now.replace(second=0, microsecond=0) + timedelta(minutes=10),
                day_start + timedelta(hours=8),
            )
        else:
            start = day_start + timedelta(hours=9)
        day_end = day_start + timedelta(days=1)
        if start >= day_end:
            return []
        cursor = start
        remaining = min(
            available_minutes,
            int((day_end - cursor).total_seconds() // 60),
        )

        candidates: list[tuple[Task, PriorityAssessment]] = []
        try:
            pending = self.task_repository.list(status="pending", sort_by="due_at", order="asc")
            counts = self.task_repository.count_subtasks_for_parents(
                [task.id for task in pending if task.parent_id is None]
            )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        for task in pending:
            total_children = counts.get(task.id, (0, 0))[0]
            if total_children:
                continue  # container task: schedule its subtasks instead
            assessment = self.priority_service.assess(task, None, now=now)
            candidates.append((task, assessment))
        candidates.sort(
            key=lambda pair: (
                -pair[1].score,
                pair[0].due_at.timestamp() if pair[0].due_at else float("inf"),
                pair[0].created_at.timestamp(),
            )
        )

        blocks: list[dict[str, object]] = []
        for task, assessment in candidates:
            if len(blocks) >= MAX_SUGGESTED_BLOCKS or remaining <= 0:
                break
            duration = task.estimated_minutes or DEFAULT_ESTIMATE_MINUTES
            estimated = task.estimated_minutes is None
            if duration > remaining:
                continue
            block_start = cursor
            block_end = cursor + timedelta(minutes=duration)
            reasons = list(assessment.reasons)
            if estimated:
                reasons.append("未填写预计耗时，按 30 分钟估算")
            if task.due_at is not None and block_end > task.due_at:
                reasons.append("按该时长安排会晚于截止时间，请确认")
            blocks.append(
                {
                    "task_id": task.id,
                    "title": task.title,
                    "priority": task.priority,
                    "estimated_minutes": duration,
                    "is_estimate": estimated,
                    "start_at": block_start.astimezone(UTC),
                    "end_at": block_end.astimezone(UTC),
                    "reasons": reasons,
                }
            )
            cursor = block_end
            remaining -= duration

        return blocks
