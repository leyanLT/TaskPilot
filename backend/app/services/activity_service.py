"""Append-only activity recording for tasks and projects.

Activities are written inside the same transaction as the change they describe:
a rolled-back write therefore never leaves a success record behind.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.database import utc_now
from app.models import Project, Task, TaskActivity
from app.repositories.activity_repository import ActivityRepository
from app.repositories.project_repository import ProjectRepository

PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
STATUS_LABELS = {"pending": "待完成", "completed": "已完成"}
PROJECT_STATUS_LABELS = {
    "planning": "规划中",
    "active": "进行中",
    "completed": "已完成",
    "archived": "已归档",
}


def format_datetime(value: datetime | None, timezone: ZoneInfo) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M")


def describe_value(field: str, value: object, timezone: ZoneInfo) -> str:
    if value is None:
        return "空"
    if field == "due_at" and isinstance(value, datetime):
        return format_datetime(value, timezone) or "空"
    if field == "priority":
        return PRIORITY_LABELS.get(str(value), str(value))
    if field == "status":
        return STATUS_LABELS.get(str(value), str(value))
    text = str(value)
    return text if len(text) <= 180 else text[:177] + "…"


class ActivityService:
    """Records and reads task/project activity.

    The repository is intentionally append-only; the service exists so every
    business write can be paired with a truthful, snapshot-based record.
    """

    def __init__(self, session: Session, *, timezone: ZoneInfo | None = None) -> None:
        self.session = session
        self.timezone = timezone or ZoneInfo("UTC")
        self.repository = ActivityRepository(session)
        self.project_repository = ProjectRepository(session)

    def project_name(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        project = self.project_repository.get(project_id)
        return project.name if project else None

    def record(
        self,
        *,
        action: str,
        summary: str,
        task: Task | None = None,
        project: Project | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        field: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        created_at: datetime | None = None,
    ) -> TaskActivity:
        resolved_project_id = (
            project.id if project else (project_id or (task.project_id if task else None))
        )
        resolved_project_name = (
            project.name if project else (project_name or self.project_name(resolved_project_id))
        )
        activity = TaskActivity(
            task_id=task.id if task else None,
            task_title=task.title if task else None,
            project_id=resolved_project_id,
            project_name=resolved_project_name,
            action=action,
            field=field,
            old_value=(old_value[:200] if old_value else None),
            new_value=(new_value[:200] if new_value else None),
            summary=summary[:300],
            created_at=created_at or utc_now(),
        )
        return self.repository.add(activity)

    def list_activities(
        self,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[TaskActivity]:
        return self.repository.list(
            project_id=project_id,
            task_id=task_id,
            since=since,
            until=until,
            limit=max(1, min(limit, 200)),
        )


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()
