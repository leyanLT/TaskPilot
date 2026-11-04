"""Focus sessions: server-authoritative timing, pause/resume and statistics.

The server owns the clock. A session stores ``accumulated_seconds`` plus the
moment it was last resumed; elapsed time is always derived from those values, so
refreshing the page or resending a request can never double-count time.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    FocusConflictError,
    FocusNotFoundError,
    TaskNotFoundError,
)
from app.models import FocusSession, Task
from app.repositories.v2_repository import FocusRepository, PreferenceRepository
from app.schemas_v2 import FocusDayRead, FocusRead, FocusStart, FocusStatsRead, FocusTaskRead

DEFAULT_FOCUS_MINUTES = 25


class FocusService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.repository = FocusRepository(session)
        self.preferences = PreferenceRepository(session)

    # -- helpers ---------------------------------------------------------

    def _flush(self, *, commit: bool = True) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise FocusConflictError("已经有一个专注会话在进行，请先结束它。") from exc
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    @staticmethod
    def _elapsed_seconds(row: FocusSession, now: datetime) -> int:
        elapsed = row.accumulated_seconds
        if row.status == "running" and row.last_resumed_at is not None:
            elapsed += max(0, int((now - row.last_resumed_at).total_seconds()))
        return max(0, elapsed)

    @classmethod
    def elapsed_seconds(cls, row: FocusSession, now: datetime | None = None) -> int:
        """Public, side-effect-free elapsed time used by reports and the API."""

        return cls._elapsed_seconds(row, now or utc_now())

    def _default_minutes(self) -> int:
        preference = self.preferences.get()
        return preference.default_focus_minutes if preference else DEFAULT_FOCUS_MINUTES

    def _view(self, row: FocusSession, now: datetime | None = None) -> FocusRead:
        now = now or utc_now()
        task = self.session.get(Task, row.task_id)
        elapsed = self._elapsed_seconds(row, now)
        target = row.planned_minutes * 60 if row.planned_minutes else None
        return FocusRead(
            id=UUID(row.id),
            task_id=UUID(row.task_id),
            task_title=task.title if task else "（任务已删除）",
            task_estimated_minutes=task.estimated_minutes if task else None,
            status=row.status,
            mode=row.mode,
            planned_minutes=row.planned_minutes,
            elapsed_seconds=elapsed,
            accumulated_seconds=row.accumulated_seconds,
            target_seconds=target,
            remaining_seconds=max(0, target - elapsed) if target else None,
            started_at=row.started_at,
            last_resumed_at=row.last_resumed_at,
            ended_at=row.ended_at,
            synced_at=now,
        )

    def _require(self, session_id: str) -> FocusSession:
        row = self.repository.get(session_id)
        if row is None:
            raise FocusNotFoundError()
        return row

    # -- lifecycle -------------------------------------------------------

    def start(self, data: FocusStart) -> FocusRead:
        task = self.session.get(Task, str(data.task_id))
        if task is None:
            raise TaskNotFoundError()
        if task.status == "completed":
            raise FocusConflictError("这个任务已经完成了，选一个待完成任务再开始专注。")
        active = self.repository.active()
        if active is not None:
            if active.task_id == task.id:
                return self._view(active)
            other = self.session.get(Task, active.task_id)
            raise FocusConflictError(
                f"「{other.title if other else '另一个任务'}」正在专注中，先结束它再开始新的专注。",
                details={"active_session_id": active.id, "active_task_id": active.task_id},
            )
        now = utc_now()
        planned = data.planned_minutes or self._default_minutes()
        row = FocusSession(
            task_id=task.id,
            status="running",
            mode=data.mode,
            planned_minutes=planned,
            accumulated_seconds=0,
            started_at=now,
            last_resumed_at=now,
            note=data.note,
        )
        try:
            self.repository.add(row)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush()
        return self._view(row)

    def pause(self, session_id: str) -> FocusRead:
        row = self._require(session_id)
        if row.status == "completed":
            raise FocusConflictError("这个专注会话已经结束了。")
        now = utc_now()
        if row.status == "paused":
            return self._view(row, now)
        row.accumulated_seconds += (
            max(0, int((now - row.last_resumed_at).total_seconds())) if row.last_resumed_at else 0
        )
        row.status = "paused"
        row.last_resumed_at = None
        self._flush()
        return self._view(row, now)

    def resume(self, session_id: str) -> FocusRead:
        row = self._require(session_id)
        if row.status == "completed":
            raise FocusConflictError("这个专注会话已经结束了，请重新开始。")
        now = utc_now()
        if row.status == "running":
            return self._view(row, now)
        row.status = "running"
        row.last_resumed_at = now
        self._flush()
        return self._view(row, now)

    def stop(self, session_id: str) -> FocusRead:
        """Idempotent: stopping an already finished session returns it unchanged."""

        row = self._require(session_id)
        now = utc_now()
        if row.status == "completed":
            return self._view(row, now)
        if row.status == "running" and row.last_resumed_at is not None:
            row.accumulated_seconds += max(0, int((now - row.last_resumed_at).total_seconds()))
        row.status = "completed"
        row.ended_at = now
        row.last_resumed_at = None
        self._flush()
        return self._view(row, now)

    # -- reads -----------------------------------------------------------

    def active(self) -> FocusRead | None:
        row = self.repository.active()
        return self._view(row) if row else None

    def get(self, session_id: str) -> FocusRead:
        return self._view(self._require(session_id))

    def task_seconds(self, task_id: str) -> int:
        now = utc_now()
        return sum(
            self._elapsed_seconds(row, now)
            for row in self.repository.for_task(task_id)
            if row.status in ("running", "paused", "completed")
        )

    def stats(self, *, reference: date | None = None) -> FocusStatsRead:
        today = reference or utc_now().astimezone(self.timezone).date()
        week_start = today - timedelta(days=today.weekday())
        range_start = datetime.combine(week_start, time.min, tzinfo=self.timezone).astimezone(UTC)
        range_end = datetime.combine(
            today + timedelta(days=1), time.min, tzinfo=self.timezone
        ).astimezone(UTC)
        rows = self.repository.started_between(range_start, range_end)
        now = utc_now()
        by_day: dict[date, int] = {week_start + timedelta(days=index): 0 for index in range(7)}
        by_task: dict[str, int] = {}
        titles: dict[str, str] = {}
        today_seconds = 0
        week_seconds = 0
        for row in rows:
            seconds = self._elapsed_seconds(row, now)
            local_day = row.started_at.astimezone(self.timezone).date()
            week_seconds += seconds
            if local_day == today:
                today_seconds += seconds
            if local_day in by_day:
                by_day[local_day] += seconds
            by_task[row.task_id] = by_task.get(row.task_id, 0) + seconds
            if row.task_id not in titles:
                task = self.session.get(Task, row.task_id)
                titles[row.task_id] = task.title if task else "（任务已删除）"
        ordered_tasks = sorted(by_task.items(), key=lambda item: item[1], reverse=True)[:5]
        return FocusStatsRead(
            today=today.isoformat(),
            today_seconds=today_seconds,
            week_seconds=week_seconds,
            session_count=len(rows),
            by_day=[FocusDayRead(date=day, seconds=seconds) for day, seconds in by_day.items()],
            by_task=[
                FocusTaskRead(task_id=UUID(task_id), title=titles[task_id], seconds=seconds)
                for task_id, seconds in ordered_tasks
            ],
        )

    @staticmethod
    def remaining_work_minutes(
        task: Task, focused_seconds: int, elapsed_planned: int = 0
    ) -> int | None:
        """Rough remaining workload from the estimate, never a fabricated fact."""

        if task.estimated_minutes is None:
            return None
        spent = math.ceil(focused_seconds / 60) + max(0, elapsed_planned)
        return max(0, task.estimated_minutes - spent)
