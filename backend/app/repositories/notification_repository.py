"""Database access for in-app notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import Notification


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, notification_id: str) -> Notification | None:
        return self.session.get(Notification, notification_id)

    def existing_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        statement = select(Notification.dedupe_key).where(Notification.dedupe_key.in_(keys))
        return set(self.session.scalars(statement))

    def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        self.session.flush()
        return notification

    def list(
        self,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[Notification]:
        statement = select(Notification)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        statement = statement.order_by(
            Notification.read_at.is_(None).desc(),
            Notification.created_at.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def unread_count(self) -> int:
        statement = select(func.count(Notification.id)).where(Notification.read_at.is_(None))
        return int(self.session.execute(statement).scalar() or 0)

    def mark_read(self, notification_id: str, *, now: datetime | None) -> bool:
        statement = (
            update(Notification).where(Notification.id == notification_id).values(read_at=now)
        )
        return bool(self.session.execute(statement).rowcount)

    def mark_all_read(self, *, now: datetime) -> int:
        statement = update(Notification).where(Notification.read_at.is_(None)).values(read_at=now)
        return int(self.session.execute(statement).rowcount or 0)

    def delete_for_completed_tasks(self) -> int:
        """Remove stale reminder rows for tasks that are no longer open."""

        from app.models import Task

        open_task_ids = select(Task.id).where(Task.status == "pending")
        statement = delete(Notification).where(
            Notification.task_id.is_not(None),
            Notification.task_id.not_in(open_task_ids),
        )
        return int(self.session.execute(statement).rowcount or 0)

    def delete_not_in(self, keys: list[str]) -> int:
        """Drop derived reminders that are no longer valid (completion, new due date)."""

        if not keys:
            statement = delete(Notification)
        else:
            statement = delete(Notification).where(Notification.dedupe_key.not_in(keys))
        return int(self.session.execute(statement).rowcount or 0)

    def counts_by_type(self) -> dict[str, int]:
        statement = select(Notification.type, func.count(Notification.id)).group_by(
            Notification.type
        )
        return {str(row[0]): int(row[1]) for row in self.session.execute(statement)}
