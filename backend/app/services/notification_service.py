"""Derived in-app reminders for due-soon, overdue, and today's tasks.

Reminders are generated deterministically from real task rows each time the
notification center is read, so the state survives restarts without a queue or
a background scheduler. ``dedupe_key`` makes generation idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import DatabaseOperationError, NotificationNotFoundError
from app.models import Notification, Task
from app.repositories.notification_repository import NotificationRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import NotificationList, NotificationRead, NotificationType, TaskStatus

DUE_SOON_WINDOW = timedelta(hours=24)
TYPE_LABELS = {
    "today_todo": "今日待办",
    "due_soon": "即将截止",
    "overdue": "已逾期",
}


class NotificationService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.repository = NotificationRepository(session)
        self.task_repository = TaskRepository(session)

    def _rollback(self) -> None:
        try:
            self.session.rollback()
        except SQLAlchemyError:
            pass

    def _commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _desired(self, now: datetime) -> list[dict[str, object]]:
        local_now = now.astimezone(self.timezone)
        today = local_now.date()
        desired: list[dict[str, object]] = []
        try:
            tasks = self.task_repository.list()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

        for task in tasks:
            if task.status != TaskStatus.pending.value or task.due_at is None:
                continue
            due_at = task.due_at
            due_local = due_at.astimezone(self.timezone)
            due_key = due_at.astimezone(UTC).isoformat()

            if due_at < now:
                desired.append(
                    {
                        "type": NotificationType.overdue.value,
                        "task": task,
                        "dedupe_key": f"overdue:{task.id}:{due_key}",
                        "message": (
                            f"「{task.title}」已于 {due_local.strftime('%m月%d日 %H:%M')} 逾期"
                        ),
                    }
                )
            elif due_at <= now + DUE_SOON_WINDOW:
                hours = max(1, int((due_at - now).total_seconds() // 3600))
                desired.append(
                    {
                        "type": NotificationType.due_soon.value,
                        "task": task,
                        "dedupe_key": f"due_soon:{task.id}:{due_key}",
                        "message": (
                            f"「{task.title}」将在 {hours} 小时内截止"
                            f"（{due_local.strftime('%m月%d日 %H:%M')}）"
                        ),
                    }
                )

            if due_local.date() == today:
                desired.append(
                    {
                        "type": NotificationType.today_todo.value,
                        "task": task,
                        "dedupe_key": f"today_todo:{task.id}:{today.isoformat()}",
                        "message": f"今天要完成「{task.title}」",
                    }
                )
        return desired

    def sync(self, *, now: datetime | None = None) -> None:
        """Create missing reminders, drop stale ones, and clear completed tasks."""

        now = now or utc_now()
        desired = self._desired(now)
        keys = [str(item["dedupe_key"]) for item in desired]
        try:
            existing = self.repository.existing_keys(keys)
            for item in desired:
                key = str(item["dedupe_key"])
                if key in existing:
                    continue
                task = item["task"]
                assert isinstance(task, Task)
                self.repository.add(
                    Notification(
                        type=str(item["type"]),
                        task_id=task.id,
                        task_title=task.title,
                        message=str(item["message"]),
                        due_at=task.due_at,
                        dedupe_key=key,
                        created_at=now,
                    )
                )
            self.repository.delete_not_in(keys)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._commit()

    # ------------------------------------------------------------------
    # Reads and read-state
    # ------------------------------------------------------------------

    def list(
        self,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> NotificationList:
        self.sync()
        try:
            rows = self.repository.list(unread_only=unread_only, limit=limit)
            unread = self.repository.unread_count()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return NotificationList(
            items=[NotificationRead.model_validate(row) for row in rows],
            unread_count=unread,
        )

    def unread_count(self) -> int:
        self.sync()
        try:
            return self.repository.unread_count()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def mark_read(self, notification_id: str | UUID, *, read: bool = True) -> NotificationRead:
        notification = self.repository.get(str(notification_id))
        if notification is None:
            raise NotificationNotFoundError()
        now = utc_now() if read else None
        try:
            self.repository.mark_read(notification.id, now=now)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._commit()
        refreshed = self.repository.get(notification.id)
        if refreshed is None:
            raise NotificationNotFoundError()
        return NotificationRead.model_validate(refreshed)

    def mark_all_read(self) -> int:
        try:
            count = self.repository.mark_all_read(now=utc_now())
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._commit()
        return count
