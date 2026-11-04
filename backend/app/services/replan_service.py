"""Deterministic replanning with a review step.

The LLM never computes the schedule. This service builds a capacity- and
dependency-aware proposal from real task data, explains every decision in plain
language, and only writes after the user confirms. A plan token fingerprints the
current plan so a stale proposal is rejected instead of overwriting newer data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    PlanVersionConflictError,
    TaskNotFoundError,
)
from app.models import PlanRevision, Task
from app.repositories.v2_repository import (
    PlanRevisionRepository,
    PreferenceRepository,
    TaskDependencyRepository,
)
from app.schemas import PlanItemInput, PlanUpsert
from app.schemas_v2 import (
    ReplanBlockRead,
    ReplanChangeRead,
    ReplanDraftRead,
)
from app.services.dependency_service import DependencyService
from app.services.planning_service import DEFAULT_ESTIMATE_MINUTES, PlanningService
from app.services.priority_service import PriorityService

MAX_BLOCKS = 10
DEFAULT_DAY_MINUTES = 600


class ReplanService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.planning = PlanningService(session, timezone=timezone)
        self.priority = PriorityService(session, timezone=timezone)
        self.dependencies = DependencyService(session)
        self.revisions = PlanRevisionRepository(session)
        self.preferences = PreferenceRepository(session)
        self.dependency_rows = TaskDependencyRepository(session)

    # -- helpers ---------------------------------------------------------

    def _available_minutes(self, plan_date: date, override: int | None) -> int:
        if override:
            return override
        plan = self.planning.repository.get_by_date(plan_date)
        if plan is not None:
            return plan.available_minutes
        preference = self.preferences.get()
        if preference is not None:
            return preference.daily_available_minutes
        return DEFAULT_DAY_MINUTES

    def _current_blocks(self, plan_date: date) -> list[dict[str, object]]:
        plan = self.planning.get_plan_or_none(plan_date)
        if plan is None:
            return []
        return [
            {
                "task_id": str(item.task_id),
                "title": item.task_title,
                "start_at": item.start_at.isoformat(),
                "end_at": item.end_at.isoformat(),
            }
            for item in plan.items
        ]

    @staticmethod
    def _token(blocks: list[dict[str, object]]) -> str:
        payload = json.dumps(
            sorted(
                (
                    block["task_id"],
                    block["start_at"],
                    block["end_at"],
                )
                for block in blocks
            ),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _window(self, plan_date: date, now: datetime) -> tuple[datetime, datetime]:
        day_start = datetime.combine(plan_date, time.min, tzinfo=self.timezone)
        day_end = day_start + timedelta(days=1)
        if plan_date == now.astimezone(self.timezone).date():
            start = max(
                now.astimezone(self.timezone).replace(second=0, microsecond=0)
                + timedelta(minutes=10),
                day_start + timedelta(hours=8),
            )
        else:
            start = day_start + timedelta(hours=9)
        return start, min(day_end, start + timedelta(minutes=DEFAULT_DAY_MINUTES))

    def _unavailable(self, windows: list[dict[str, str]]) -> list[tuple[datetime, datetime]]:
        parsed: list[tuple[datetime, datetime]] = []
        for window in windows:
            try:
                start = datetime.fromisoformat(window["start"]).astimezone(UTC)
                end = datetime.fromisoformat(window["end"]).astimezone(UTC)
            except (KeyError, ValueError, TypeError):
                continue
            if end > start:
                parsed.append((start, end))
        return sorted(parsed)

    @staticmethod
    def _overlaps(
        start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]
    ) -> tuple[datetime, datetime] | None:
        for busy_start, busy_end in busy:
            if start < busy_end and end > busy_start:
                return busy_start, busy_end
        return None

    # -- proposal --------------------------------------------------------

    def preview(
        self,
        *,
        plan_date: date | None = None,
        reason: str = "",
        available_minutes: int | None = None,
        keep_task_ids: list[UUID] | None = None,
        unavailable_windows: list[dict[str, str]] | None = None,
    ) -> ReplanDraftRead:
        now = utc_now()
        target_day = plan_date or now.astimezone(self.timezone).date()
        capacity = self._available_minutes(target_day, available_minutes)
        before = self._current_blocks(target_day)
        before_by_task = {block["task_id"]: block for block in before}
        keep = {str(task_id) for task_id in (keep_task_ids or [])}

        pending = list(
            self.session.scalars(
                select(Task).where(Task.status == "pending").order_by(Task.created_at)
            )
        )
        child_counts = self.session.execute(
            select(Task.parent_id).where(Task.parent_id.is_not(None))
        )
        parent_ids = {row[0] for row in child_counts}
        blocked = self.dependencies.blocked_titles([task.id for task in pending])

        candidates: list[Task] = []
        blocked_tasks: list[dict[str, object]] = []
        for task in pending:
            if task.id in parent_ids:
                continue  # container task: its subtasks do the work
            if task.id in blocked:
                blocked_tasks.append(
                    {"task_id": task.id, "title": task.title, "blocked_by": blocked[task.id]}
                )
                continue
            candidates.append(task)

        # Blocks of tasks that are being rescheduled do not block themselves;
        # only fixed commitments (completed work, other tasks) and the caller's
        # unavailable windows constrain the new proposal.
        candidate_ids = {task.id for task in candidates}
        busy: list[tuple[datetime, datetime]] = []
        for block in before:
            if block["task_id"] in candidate_ids:
                continue
            try:
                busy.append(
                    (
                        datetime.fromisoformat(str(block["start_at"])),
                        datetime.fromisoformat(str(block["end_at"])),
                    )
                )
            except ValueError:  # pragma: no cover - stored ISO strings
                continue
        busy.extend(self._unavailable(unavailable_windows or []))
        window_start, window_end = self._window(target_day, now)
        busy = [segment for segment in busy if segment[1] > window_start]

        assessments = {task.id: self.priority.assess(task, None, now=now) for task in candidates}
        candidates.sort(
            key=lambda task: (
                0 if task.id in keep else 1,
                -assessments[task.id].score,
                task.due_at.timestamp() if task.due_at else float("inf"),
                task.created_at.timestamp(),
            )
        )

        cursor = window_start
        remaining = min(capacity, int((window_end - cursor).total_seconds() // 60))
        after: list[dict[str, object]] = []
        unscheduled: list[dict[str, object]] = []
        reasons_for: dict[str, list[str]] = {}
        for task in candidates:
            if len(after) >= MAX_BLOCKS or remaining <= 0:
                unscheduled.append(
                    {"task_id": task.id, "title": task.title, "blocked_by": ["时间不够"]}
                )
                continue
            duration = task.estimated_minutes or DEFAULT_ESTIMATE_MINUTES
            if duration > remaining:
                unscheduled.append(
                    {"task_id": task.id, "title": task.title, "blocked_by": ["剩余时间不足"]}
                )
                continue
            start = cursor
            end = start + timedelta(minutes=duration)
            conflict = self._overlaps(start, end, busy)
            if conflict is not None:
                start = conflict[1]
                end = start + timedelta(minutes=duration)
                if end > window_end:
                    unscheduled.append(
                        {"task_id": task.id, "title": task.title, "blocked_by": ["时间被占用"]}
                    )
                    continue
            reasons = list(assessments[task.id].reasons)
            if task.estimated_minutes is None:
                reasons.append("未填写预计耗时，按 30 分钟估算")
            if task.due_at is not None and end > task.due_at:
                reasons.append("按该时长安排会晚于截止时间，请确认")
            after.append(
                {
                    "task_id": task.id,
                    "title": task.title,
                    "priority": task.priority,
                    "estimated_minutes": duration,
                    "start_at": start,
                    "end_at": end,
                    "reasons": reasons,
                }
            )
            reasons_for[task.id] = reasons
            busy.append((start, end))
            cursor = end
            remaining -= int((end - start).total_seconds() // 60)

        changes: list[ReplanChangeRead] = []
        after_by_task = {str(block["task_id"]): block for block in after}
        for task_id, block in after_by_task.items():
            previous = before_by_task.get(task_id)
            start = block["start_at"]
            if previous is None:
                changes.append(
                    ReplanChangeRead(
                        kind="added",
                        task_id=UUID(task_id),
                        title=str(block["title"]),
                        after_start=start,
                    )
                )
            elif datetime.fromisoformat(str(previous["start_at"])) != start:
                changes.append(
                    ReplanChangeRead(
                        kind="moved",
                        task_id=UUID(task_id),
                        title=str(block["title"]),
                        before_start=datetime.fromisoformat(str(previous["start_at"])),
                        after_start=start,
                    )
                )
            else:
                changes.append(
                    ReplanChangeRead(
                        kind="kept",
                        task_id=UUID(task_id),
                        title=str(block["title"]),
                        before_start=start,
                        after_start=start,
                    )
                )
        for task_id, block in before_by_task.items():
            if task_id not in after_by_task:
                changes.append(
                    ReplanChangeRead(
                        kind="removed",
                        task_id=UUID(task_id),
                        title=str(block["title"]),
                        before_start=datetime.fromisoformat(str(block["start_at"])),
                    )
                )

        explanation = self._explain(
            target_day, capacity, before, after, changes, blocked_tasks, unscheduled, reason
        )
        return ReplanDraftRead(
            plan_date=target_day,
            available_minutes=capacity,
            before=[self._block_view(block) for block in before],
            after=[self._block_view(block) for block in after],
            changes=changes,
            blocked_tasks=[self._blocked_view(item) for item in blocked_tasks],
            unscheduled=[self._blocked_view(item) for item in unscheduled],
            explanation=explanation,
            plan_token=self._token(before),
        )

    @staticmethod
    def _block_view(block: dict[str, object]) -> ReplanBlockRead:
        return ReplanBlockRead(
            task_id=UUID(str(block["task_id"])),
            title=str(block["title"]),
            priority=str(block.get("priority", "medium")),
            estimated_minutes=int(
                max(
                    1,
                    (
                        datetime.fromisoformat(str(block["end_at"]))
                        - datetime.fromisoformat(str(block["start_at"]))
                    ).total_seconds()
                    // 60,
                )
            ),
            start_at=datetime.fromisoformat(str(block["start_at"])),
            end_at=datetime.fromisoformat(str(block["end_at"])),
            reasons=[str(reason) for reason in block.get("reasons", [])],
        )

    @staticmethod
    def _blocked_view(item: dict[str, object]) -> dict[str, object]:
        return item

    def _explain(
        self,
        plan_date: date,
        capacity: int,
        before: list[dict[str, object]],
        after: list[dict[str, object]],
        changes: list[ReplanChangeRead],
        blocked: list[dict[str, object]],
        unscheduled: list[dict[str, object]],
        reason: str,
    ) -> list[str]:
        added = sum(1 for change in changes if change.kind == "added")
        moved = sum(1 for change in changes if change.kind == "moved")
        removed = sum(1 for change in changes if change.kind == "removed")
        lines: list[str] = []
        if reason.strip():
            lines.append(f"调整原因：{reason.strip()}")
        lines.append(
            f"{plan_date.isoformat()} 可用 {capacity} 分钟，"
            f"新方案安排 {sum(int((block['end_at'] - block['start_at']).total_seconds() // 60) for block in after)} 分钟、"
            f"共 {len(after)} 个时间块。"
        )
        if added:
            lines.append(f"新增 {added} 个时间块（原来没有安排的任务）。")
        if moved:
            lines.append(f"{moved} 个时间块改变了开始时间。")
        if removed:
            lines.append(f"{removed} 个原有安排不再保留。")
        if blocked:
            lines.append(f"{len(blocked)} 个任务因为前置任务未完成被跳过。")
        if unscheduled:
            lines.append(f"{len(unscheduled)} 个任务今天放不下，建议顺延到明天。")
        if not after:
            lines.append("今天没有可以继续安排的任务，先把剩余时间留给自己。")
        return lines

    # -- apply -----------------------------------------------------------

    def plan_token(self, plan_date: date) -> str:
        return self._token(self._current_blocks(plan_date))

    def apply(
        self,
        *,
        plan_date: date,
        blocks: list[ReplanBlockRead],
        plan_token: str,
        reason: str = "",
        source: str = "user",
        action_id: str | None = None,
        commit: bool = True,
    ) -> tuple[int, int]:
        current_token = self.plan_token(plan_date)
        if plan_token and plan_token != current_token:
            raise PlanVersionConflictError()
        before = self._current_blocks(plan_date)
        items = [
            PlanItemInput(
                task_id=block.task_id,
                start_at=block.start_at,
                end_at=block.end_at,
                note=None,
            )
            for block in blocks
        ]
        plan = self.planning.repository.get_by_date(plan_date)
        capacity = plan.available_minutes if plan else self._available_minutes(plan_date, None)
        self.planning.save_plan(
            plan_date,
            PlanUpsert(items=items, available_minutes=capacity),
            commit=False,
        )
        for block in blocks:
            task = self.session.get(Task, str(block.task_id))
            if task is None:
                raise TaskNotFoundError()
        after = [
            {
                "task_id": str(block.task_id),
                "title": block.title,
                "start_at": block.start_at.isoformat(),
                "end_at": block.end_at.isoformat(),
            }
            for block in blocks
        ]
        revision = PlanRevision(
            plan_date=plan_date,
            revision_no=self.revisions.next_number(plan_date),
            source=source,
            reason=reason or None,
            before_items=before,
            after_items=after,
            action_id=action_id,
        )
        try:
            self.revisions.add(revision)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        return len(blocks), revision.revision_no
