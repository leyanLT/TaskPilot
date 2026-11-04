"""Aggregated dashboard read model built from real task/project/plan data."""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.database import utc_now
from app.models import Task
from app.repositories.task_repository import TaskRepository
from app.schemas import (
    ActivityRead,
    DashboardCounts,
    DashboardResponse,
    TaskRead,
)
from app.services.activity_service import ActivityService
from app.services.notification_service import NotificationService
from app.services.planning_service import PlanningService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService

DASHBOARD_PROJECT_LIMIT = 6
DASHBOARD_TASK_LIMIT = 8
DASHBOARD_ACTIVITY_LIMIT = 8


class DashboardService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.task_repository = TaskRepository(session)
        self.task_service = TaskService(session, timezone=timezone)
        self.project_service = ProjectService(session, timezone=timezone)
        self.planning_service = PlanningService(session, timezone=timezone)
        self.notification_service = NotificationService(session, timezone=timezone)
        self.activity_service = ActivityService(session, timezone=timezone)

    def build(self) -> DashboardResponse:
        now = utc_now()
        local_today = now.astimezone(self.timezone).date()

        views = self.task_service.list_task_views(
            status="pending",  # type: ignore[arg-type]
            sort_by="due_at",
            order="asc",
            root_only=True,
        )
        by_id = {str(view.id): view for view in views}
        pending_tasks = self.task_repository.list(
            status="pending", sort_by="due_at", order="asc", root_only=True
        )

        def view_for(task: Task) -> TaskRead:
            return by_id.get(task.id) or TaskRead.from_task(task)

        today_tasks = [
            view_for(task)
            for task in pending_tasks
            if task.due_at is not None
            and task.due_at.astimezone(self.timezone).date() == local_today
        ][:DASHBOARD_TASK_LIMIT]
        overdue_tasks = [
            view_for(task)
            for task in pending_tasks
            if task.due_at is not None and task.due_at < now
        ][:DASHBOARD_TASK_LIMIT]
        due_soon_tasks = [
            view_for(task)
            for task in pending_tasks
            if task.due_at is not None and now < task.due_at <= now + timedelta(hours=24)
        ][:DASHBOARD_TASK_LIMIT]

        counts = self.task_repository.status_counts(now=now, root_only=True)
        status_counts = DashboardCounts(
            total=counts["total"],
            pending=counts["pending"],
            completed=counts["completed"],
            overdue=counts["overdue"],
            due_today=len(
                [
                    task
                    for task in pending_tasks
                    if task.due_at is not None
                    and task.due_at.astimezone(self.timezone).date() == local_today
                ]
            ),
            due_soon=len(
                [
                    task
                    for task in pending_tasks
                    if task.due_at is not None and now < task.due_at <= now + timedelta(hours=24)
                ]
            ),
        )

        projects = self.project_service.list_projects(include_archived=False)
        order = {"active": 0, "planning": 1, "completed": 2, "archived": 3}
        projects.sort(key=lambda project: (order.get(project.status.value, 9), project.name))
        plan = self.planning_service.get_plan_or_none(local_today)
        activities = self.activity_service.list_activities(limit=DASHBOARD_ACTIVITY_LIMIT)
        unread = self.notification_service.unread_count()

        return DashboardResponse(
            date=local_today,
            timezone=self.timezone.key,
            counts=status_counts,
            today_tasks=today_tasks,
            due_soon_tasks=due_soon_tasks,
            overdue_tasks=overdue_tasks,
            projects=projects[:DASHBOARD_PROJECT_LIMIT],
            today_plan=plan,
            recent_activities=[ActivityRead.model_validate(activity) for activity in activities],
            unread_notifications=unread,
        )
