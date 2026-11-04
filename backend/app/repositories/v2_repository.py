"""Repositories for the V2.0 aggregates.

Only persistence concerns live here: services still own every business rule.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FocusSession,
    PlanRevision,
    RecurrenceRule,
    Task,
    TaskDependency,
    UserPreference,
)


class TaskDependencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, dependency: TaskDependency) -> TaskDependency:
        self.session.add(dependency)
        return dependency

    def get(self, dependency_id: str) -> TaskDependency | None:
        return self.session.get(TaskDependency, dependency_id)

    def delete(self, dependency: TaskDependency) -> None:
        self.session.delete(dependency)

    def for_task(self, task_id: str) -> list[TaskDependency]:
        stmt = (
            select(TaskDependency)
            .where(TaskDependency.task_id == task_id)
            .order_by(TaskDependency.created_at)
        )
        return list(self.session.scalars(stmt))

    def blocking_task(self, task_id: str) -> list[TaskDependency]:
        stmt = (
            select(TaskDependency)
            .where(TaskDependency.task_id == task_id)
            .order_by(TaskDependency.created_at)
        )
        return list(self.session.scalars(stmt))

    def depending_on(self, task_id: str) -> list[TaskDependency]:
        stmt = (
            select(TaskDependency)
            .where(TaskDependency.depends_on_task_id == task_id)
            .order_by(TaskDependency.created_at)
        )
        return list(self.session.scalars(stmt))

    def between(self, task_id: str, depends_on_task_id: str) -> TaskDependency | None:
        stmt = select(TaskDependency).where(
            TaskDependency.task_id == task_id,
            TaskDependency.depends_on_task_id == depends_on_task_id,
        )
        return self.session.scalars(stmt).first()

    def all_pairs(self) -> list[tuple[str, str]]:
        stmt = select(TaskDependency.task_id, TaskDependency.depends_on_task_id)
        return [(row[0], row[1]) for row in self.session.execute(stmt)]


class RecurrenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, rule: RecurrenceRule) -> RecurrenceRule:
        self.session.add(rule)
        return rule

    def get(self, rule_id: str) -> RecurrenceRule | None:
        return self.session.get(RecurrenceRule, rule_id)

    def list(self, *, include_paused: bool = True) -> list[RecurrenceRule]:
        stmt = select(RecurrenceRule).order_by(RecurrenceRule.created_at)
        if not include_paused:
            stmt = stmt.where(RecurrenceRule.paused.is_(False))
        return list(self.session.scalars(stmt))

    def delete(self, rule: RecurrenceRule) -> None:
        self.session.delete(rule)

    def instances(self, rule_id: str) -> list[Task]:
        stmt = select(Task).where(Task.recurrence_rule_id == rule_id).order_by(Task.occurrence_date)
        return list(self.session.scalars(stmt))

    def existing_dates(self, rule_id: str) -> set[date]:
        stmt = select(Task.occurrence_date).where(
            Task.recurrence_rule_id == rule_id,
            Task.occurrence_date.is_not(None),
        )
        return {row[0] for row in self.session.execute(stmt)}


class FocusRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, session_row: FocusSession) -> FocusSession:
        self.session.add(session_row)
        return session_row

    def get(self, session_id: str) -> FocusSession | None:
        return self.session.get(FocusSession, session_id)

    def active(self) -> FocusSession | None:
        stmt = select(FocusSession).where(FocusSession.status.in_(("running", "paused")))
        return self.session.scalars(stmt).first()

    def for_task(self, task_id: str, limit: int = 20) -> list[FocusSession]:
        stmt = (
            select(FocusSession)
            .where(FocusSession.task_id == task_id)
            .order_by(FocusSession.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def started_between(self, start: datetime, end: datetime) -> list[FocusSession]:
        stmt = (
            select(FocusSession)
            .where(
                FocusSession.started_at >= start,
                FocusSession.started_at < end,
                FocusSession.status.in_(("running", "paused", "completed")),
            )
            .order_by(FocusSession.started_at)
        )
        return list(self.session.scalars(stmt))

    def unfinished_for_task(self, task_id: str) -> FocusSession | None:
        stmt = select(FocusSession).where(
            FocusSession.task_id == task_id,
            FocusSession.status.in_(("running", "paused")),
        )
        return self.session.scalars(stmt).first()


class PlanRevisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, revision: PlanRevision) -> PlanRevision:
        self.session.add(revision)
        return revision

    def next_number(self, plan_date: date) -> int:
        stmt = (
            select(PlanRevision.revision_no)
            .where(PlanRevision.plan_date == plan_date)
            .order_by(PlanRevision.revision_no.desc())
            .limit(1)
        )
        current = self.session.scalars(stmt).first()
        return (current or 0) + 1

    def for_date(self, plan_date: date) -> list[PlanRevision]:
        stmt = (
            select(PlanRevision)
            .where(PlanRevision.plan_date == plan_date)
            .order_by(PlanRevision.revision_no.desc())
        )
        return list(self.session.scalars(stmt))


class PreferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> UserPreference | None:
        return self.session.get(UserPreference, "default")

    def save(self, preference: UserPreference) -> UserPreference:
        self.session.add(preference)
        return preference
