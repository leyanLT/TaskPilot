"""Project business rules: CRUD, archive/restore, progress, recent activity."""

from __future__ import annotations

from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    InvalidDateRangeError,
    ProjectNotFoundError,
)
from app.models import Project
from app.repositories.activity_repository import ActivityRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import (
    ActivityRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectStats,
    ProjectStatus,
    ProjectUpdate,
    TaskRead,
)
from app.services.activity_service import PROJECT_STATUS_LABELS, ActivityService


class ProjectService:
    """Projects group tasks. Progress is always derived from real task rows."""

    def __init__(self, session: Session, *, timezone: ZoneInfo | None = None) -> None:
        self.session = session
        self.timezone = timezone or ZoneInfo("UTC")
        self.repository = ProjectRepository(session)
        self.task_repository = TaskRepository(session)
        self.activity_repository = ActivityRepository(session)
        self.activities = ActivityService(session, timezone=self.timezone)

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

    def get_project(self, project_id: str | UUID) -> Project:
        try:
            project = self.repository.get(str(project_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        if project is None:
            raise ProjectNotFoundError()
        return project

    def stats(self, project_id: str | UUID) -> ProjectStats:
        try:
            total, completed, pending, overdue = self.task_repository.project_status_counts(
                str(project_id), now=utc_now()
            )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        rate = round(completed / total * 100, 1) if total else 0.0
        return ProjectStats(
            total_tasks=total,
            completed_tasks=completed,
            pending_tasks=pending,
            overdue_tasks=overdue,
            completion_rate=rate,
        )

    def project_view(self, project: Project) -> ProjectRead:
        return ProjectRead.from_project(project, self.stats(project.id))

    def list_projects(
        self,
        *,
        status: ProjectStatus | None = None,
        include_archived: bool = True,
        search: str | None = None,
    ) -> list[ProjectRead]:
        try:
            projects = self.repository.list(
                status=status.value if status else None,
                include_archived=include_archived,
                search=search,
            )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return [self.project_view(project) for project in projects]

    def get_project_detail(self, project_id: str | UUID) -> ProjectDetail:
        project = self.get_project(project_id)
        try:
            rows = self.task_repository.list_with_counts(
                project_id=project.id,
                sort_by="created_at",
                order="desc",
                root_only=True,
            )
            activities = self.activity_repository.list(project_id=project.id, limit=10)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return ProjectDetail(
            project=self.project_view(project),
            tasks=[
                TaskRead.from_task(
                    task,
                    subtask_count=total,
                    completed_subtask_count=completed,
                )
                for task, total, completed in rows
            ],
            recent_activities=[ActivityRead.model_validate(item) for item in activities],
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_project(self, data: ProjectCreate, *, commit: bool = True) -> Project:
        project = Project(
            name=data.name,
            description=data.description,
            status=(data.status or ProjectStatus.planning).value,
            start_date=data.start_date,
            due_date=data.due_date,
        )
        try:
            self.repository.add(project)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self.activities.record(
            action="project_created",
            summary=f"创建项目「{project.name}」",
            project=project,
        )
        self._flush(commit=commit)
        return project

    def update_project(
        self,
        project_id: str | UUID,
        data: ProjectUpdate,
        *,
        commit: bool = True,
    ) -> Project:
        project = self.get_project(project_id)
        fields = data.model_dump(exclude_unset=True)
        now = utc_now()

        if "status" in fields and fields["status"] is not None:
            status = fields["status"]
            new_status = status.value if hasattr(status, "value") else str(status)
            if new_status != project.status:
                old_status = project.status
                project.status = new_status
                self.activities.record(
                    action="project_status_changed",
                    summary=(
                        f"项目「{project.name}」状态："
                        f"{PROJECT_STATUS_LABELS.get(old_status, old_status)} → "
                        f"{PROJECT_STATUS_LABELS.get(new_status, new_status)}"
                    ),
                    project=project,
                    field="status",
                    old_value=PROJECT_STATUS_LABELS.get(old_status, old_status),
                    new_value=PROJECT_STATUS_LABELS.get(new_status, new_status),
                )

        start_date = fields.get("start_date", project.start_date)
        due_date = fields.get("due_date", project.due_date)
        if start_date and due_date and due_date < start_date:
            raise InvalidDateRangeError()

        for field in ("name", "description", "start_date", "due_date"):
            if field not in fields:
                continue
            value = fields[field]
            old_value = getattr(project, field)
            if old_value == value:
                continue
            setattr(project, field, value)
            self.activities.record(
                action="project_updated",
                summary=f"修改项目「{project.name}」：{self._field_label(field)}",
                project=project,
                field=field,
                old_value=str(old_value) if old_value else "空",
                new_value=str(value) if value else "空",
            )

        project.updated_at = now
        self._flush(commit=commit)
        return project

    @staticmethod
    def _field_label(field: str) -> str:
        return {
            "name": "名称",
            "description": "描述",
            "start_date": "开始日期",
            "due_date": "截止日期",
        }.get(field, field)

    def archive_project(self, project_id: str | UUID, *, commit: bool = True) -> Project:
        project = self.get_project(project_id)
        if project.status != ProjectStatus.archived.value:
            old_status = project.status
            project.status = ProjectStatus.archived.value
            project.updated_at = utc_now()
            self.activities.record(
                action="project_status_changed",
                summary=f"归档项目「{project.name}」，历史任务与活动保持不变",
                project=project,
                field="status",
                old_value=PROJECT_STATUS_LABELS.get(old_status, old_status),
                new_value=PROJECT_STATUS_LABELS["archived"],
            )
        self._flush(commit=commit)
        return project

    def restore_project(self, project_id: str | UUID, *, commit: bool = True) -> Project:
        project = self.get_project(project_id)
        if project.status == ProjectStatus.archived.value:
            project.status = ProjectStatus.active.value
            project.updated_at = utc_now()
            self.activities.record(
                action="project_status_changed",
                summary=f"恢复项目「{project.name}」为进行中",
                project=project,
                field="status",
                old_value=PROJECT_STATUS_LABELS["archived"],
                new_value=PROJECT_STATUS_LABELS["active"],
            )
        self._flush(commit=commit)
        return project
