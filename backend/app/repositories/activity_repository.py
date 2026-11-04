"""Database access for the append-only task/project activity log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaskActivity


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, activity: TaskActivity) -> TaskActivity:
        self.session.add(activity)
        self.session.flush()
        return activity

    def list(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[TaskActivity]:
        statement = select(TaskActivity)
        if project_id:
            statement = statement.where(TaskActivity.project_id == project_id)
        if task_id:
            statement = statement.where(TaskActivity.task_id == task_id)
        if since:
            statement = statement.where(TaskActivity.created_at >= since)
        if until:
            statement = statement.where(TaskActivity.created_at < until)
        statement = statement.order_by(
            TaskActivity.created_at.desc(), TaskActivity.id.desc()
        ).limit(limit)
        return list(self.session.scalars(statement))
