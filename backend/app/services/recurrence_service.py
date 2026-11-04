"""Recurring tasks: deterministic occurrence math and idempotent generation.

The generator is on-demand (called on read) rather than a background scheduler.
Each occurrence is a normal task linked to the rule by
``(recurrence_rule_id, occurrence_date)``; a unique constraint in the database
makes double generation impossible even under concurrent requests.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    InvalidRecurrenceError,
    ProjectNotFoundError,
    RecurrenceNotFoundError,
    TaskNotFoundError,
)
from app.models import RecurrenceRule, Task
from app.repositories.v2_repository import RecurrenceRepository
from app.schemas_v2 import (
    RecurrenceCreate,
    RecurrenceGenerateResult,
    RecurrenceRead,
    RecurrenceUpdate,
)

GENERATION_HORIZON_DAYS = 14


def add_months(anchor: date, months: int) -> date:
    """Calendar-month arithmetic with an explicit month-end clamp rule."""

    total = (anchor.year * 12 + anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last_day))


class RecurrenceService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.repository = RecurrenceRepository(session)

    # -- helpers ---------------------------------------------------------

    def _flush(self, *, commit: bool) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    def _rule_timezone(self, rule: RecurrenceRule) -> ZoneInfo:
        try:
            return ZoneInfo(rule.timezone)
        except Exception:  # pragma: no cover - defensive, timezone is validated
            return self.timezone

    def today(self) -> date:
        return utc_now().astimezone(self.timezone).date()

    # -- occurrence math -------------------------------------------------

    def occurrence_dates(
        self,
        rule: RecurrenceRule,
        until: date,
    ) -> Iterator[date]:
        stop = until if rule.end_date is None else min(until, rule.end_date)
        if stop < rule.start_date:
            return
        if rule.frequency == "daily":
            cursor = rule.start_date
            step = max(rule.interval, 1)
            while cursor <= stop:
                yield cursor
                cursor += timedelta(days=step)
            return
        if rule.frequency == "monthly":
            index = 0
            while True:
                current = add_months(rule.start_date, index * max(rule.interval, 1))
                if current > stop:
                    return
                if current >= rule.start_date:
                    yield current
                index += 1
        weekdays = (
            sorted(rule.weekdays)
            if rule.frequency == "custom_weekly" and rule.weekdays
            else [rule.start_date.weekday()]
        )
        start_monday = rule.start_date - timedelta(days=rule.start_date.weekday())
        cursor = start_monday
        while True:
            for weekday in weekdays:
                current = cursor + timedelta(days=weekday)
                if current < rule.start_date:
                    continue
                if current > stop:
                    return
                yield current
            cursor += timedelta(weeks=max(rule.interval, 1))

    # -- generation ------------------------------------------------------

    def _due_at(self, rule: RecurrenceRule, occurrence: date) -> datetime | None:
        if not rule.due_time:
            return None
        hour, minute = (int(part) for part in rule.due_time.split(":"))
        local = datetime.combine(occurrence, time(hour, minute), tzinfo=self._rule_timezone(rule))
        return local.astimezone(UTC)

    def ensure_instances(
        self,
        rule: RecurrenceRule,
        *,
        until: date | None = None,
        commit: bool = False,
    ) -> int:
        if rule.paused:
            return 0
        horizon = until or (self.today() + timedelta(days=GENERATION_HORIZON_DAYS))
        existing = self.repository.existing_dates(rule.id)
        created = 0
        for occurrence in self.occurrence_dates(rule, horizon):
            if occurrence in existing:
                continue
            task = Task(
                title=rule.title,
                description=rule.description,
                status="pending",
                due_at=self._due_at(rule, occurrence),
                project_id=rule.project_id,
                parent_id=None,
                priority=rule.priority,
                estimated_minutes=rule.estimated_minutes,
                position=0,
                recurrence_rule_id=rule.id,
                occurrence_date=occurrence,
            )
            self.session.add(task)
            try:
                self.session.flush()
            except IntegrityError:
                # Concurrent generation lost the race: the other row wins.
                self.session.rollback()
                break
            existing.add(occurrence)
            created += 1
        if created:
            self._flush(commit=commit)
        return created

    def ensure_all(self, *, days_ahead: int = GENERATION_HORIZON_DAYS) -> RecurrenceGenerateResult:
        until = self.today() + timedelta(days=days_ahead)
        created = 0
        rules = self.repository.list(include_paused=False)
        for rule in rules:
            created += self.ensure_instances(rule, until=until, commit=False)
        if created:
            self._flush(commit=True)
        return RecurrenceGenerateResult(created=created, rules=len(rules), scanned_until=until)

    # -- views -----------------------------------------------------------

    def _view(self, rule: RecurrenceRule) -> RecurrenceRead:
        instances = self.repository.instances(rule.id)
        completed = sum(1 for task in instances if task.status == "completed")
        pending = len(instances) - completed
        next_occurrence = next(
            (
                task.occurrence_date
                for task in instances
                if task.occurrence_date and task.status == "pending"
            ),
            None,
        )
        if next_occurrence is None and not rule.paused:
            horizon = self.today() + timedelta(days=GENERATION_HORIZON_DAYS)
            upcoming = next(self.occurrence_dates(rule, horizon), None)
            next_occurrence = upcoming
        return RecurrenceRead(
            id=UUID(rule.id),
            title=rule.title,
            description=rule.description,
            project_id=UUID(rule.project_id) if rule.project_id else None,
            priority=rule.priority,
            estimated_minutes=rule.estimated_minutes,
            frequency=rule.frequency,
            interval=rule.interval,
            weekdays=list(rule.weekdays) if rule.weekdays else None,
            start_date=rule.start_date,
            end_date=rule.end_date,
            due_time=rule.due_time,
            timezone=rule.timezone,
            paused=rule.paused,
            next_occurrence=next_occurrence,
            generated_count=len(instances),
            completed_count=completed,
            pending_count=pending,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )

    def list(self) -> list[RecurrenceRead]:
        self.ensure_all()
        return [self._view(rule) for rule in self.repository.list()]

    def get(self, rule_id: str) -> RecurrenceRead:
        rule = self.repository.get(rule_id)
        if rule is None:
            raise RecurrenceNotFoundError()
        self.ensure_instances(rule, commit=True)
        return self._view(rule)

    # -- writes ----------------------------------------------------------

    def _validate_project(self, project_id: str | None) -> None:
        if project_id is None:
            return
        from app.models import Project

        if self.session.get(Project, project_id) is None:
            raise ProjectNotFoundError()

    def create(self, data: RecurrenceCreate) -> RecurrenceRead:
        if data.frequency == "monthly" and data.start_date.day > 28:
            # Explicit, documented rule: months without the day use their last day.
            pass
        project_id = str(data.project_id) if data.project_id else None
        self._validate_project(project_id)
        rule = RecurrenceRule(
            title=data.title.strip(),
            description=data.description,
            project_id=project_id,
            priority=data.priority.value,
            estimated_minutes=data.estimated_minutes,
            frequency=data.frequency,
            interval=data.interval,
            weekdays=data.weekdays,
            start_date=data.start_date,
            end_date=data.end_date,
            due_time=data.due_time,
            timezone=self.timezone.key,
            paused=False,
        )
        try:
            self.repository.add(rule)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=True)
        self.ensure_instances(rule, commit=True)
        return self._view(rule)

    def update(self, rule_id: str, data: RecurrenceUpdate) -> RecurrenceRead:
        rule = self.repository.get(rule_id)
        if rule is None:
            raise RecurrenceNotFoundError()
        payload = data.model_dump(exclude_unset=True)
        if "project_id" in payload:
            project_id = str(payload["project_id"]) if payload["project_id"] else None
            self._validate_project(project_id)
            rule.project_id = project_id
        if "weekdays" in payload:
            weekdays = payload["weekdays"]
            if weekdays is not None:
                weekdays = sorted({int(day) for day in weekdays})
            rule.weekdays = weekdays
        for field in (
            "title",
            "description",
            "priority",
            "estimated_minutes",
            "frequency",
            "interval",
            "start_date",
            "end_date",
            "due_time",
            "paused",
        ):
            if field in payload:
                value = payload[field]
                if field == "priority" and value is not None:
                    value = value.value if hasattr(value, "value") else value
                if field == "title" and value is not None:
                    value = value.strip()
                setattr(rule, field, value)
        self._validate_rule(rule)
        # Resync only from today onwards; past and completed instances are history.
        self._delete_future_pending(rule)
        self._flush(commit=True)
        if not rule.paused:
            self.ensure_instances(rule, commit=True)
        return self._view(rule)

    def _validate_rule(self, rule: RecurrenceRule) -> None:
        if rule.end_date is not None and rule.end_date < rule.start_date:
            raise InvalidRecurrenceError("结束日期不能早于开始日期。")
        if rule.frequency == "custom_weekly" and not rule.weekdays:
            raise InvalidRecurrenceError("自定义每周重复需要至少选择一个星期。")
        if rule.frequency != "custom_weekly" and rule.weekdays:
            raise InvalidRecurrenceError("只有自定义每周重复可以指定星期。")

    def _delete_future_pending(self, rule: RecurrenceRule) -> int:
        today = self.today()
        removed = 0
        for task in self.repository.instances(rule.id):
            if (
                task.status == "pending"
                and task.occurrence_date is not None
                and task.occurrence_date >= today
            ):
                self.session.delete(task)
                removed += 1
        if removed:
            self.session.flush()
        return removed

    def set_paused(self, rule_id: str, paused: bool) -> RecurrenceRead:
        rule = self.repository.get(rule_id)
        if rule is None:
            raise RecurrenceNotFoundError()
        rule.paused = paused
        self._flush(commit=True)
        if not paused:
            self.ensure_instances(rule, commit=True)
        return self._view(rule)

    def delete_series(self, rule_id: str) -> int:
        rule = self.repository.get(rule_id)
        if rule is None:
            raise RecurrenceNotFoundError()
        removed = self._delete_future_pending(rule)
        try:
            self.repository.delete(rule)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=True)
        return removed

    def delete_instance(self, rule_id: str, task_id: str) -> None:
        rule = self.repository.get(rule_id)
        if rule is None:
            raise RecurrenceNotFoundError()
        task = self.session.get(Task, task_id)
        if task is None or task.recurrence_rule_id != rule.id:
            raise TaskNotFoundError("这个任务不属于该重复规则。")
        try:
            self.session.delete(task)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=True)
