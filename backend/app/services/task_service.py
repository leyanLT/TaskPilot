"""Task business rules and transaction boundaries.

V1.5 adds projects, priorities, estimates, two-level subtasks, completion
guards, and truthful activity records while keeping every v1.0 method and its
behavior intact.
"""

from __future__ import annotations

from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    InvalidSubtaskOrderError,
    ProjectArchivedError,
    ProjectNotFoundError,
    TaskHasSubtasksError,
    TaskHasUnfinishedSubtasksError,
    TaskHierarchyError,
    TaskNotFoundError,
)
from app.models import Project, Task
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import (
    SubtaskCreate,
    TaskCreate,
    TaskDetail,
    TaskPriority,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from app.services.activity_service import ActivityService, describe_value


class TaskService:
    """All task reads and writes go through this service.

    Public mutating methods commit by default. Internal callers that need to
    combine several writes into one transaction pass ``commit=False`` and own
    the final commit/rollback.
    """

    def __init__(self, session: Session, *, timezone: ZoneInfo | None = None) -> None:
        self.session = session
        self.timezone = timezone or ZoneInfo("UTC")
        self.repository = TaskRepository(session)
        self.project_repository = ProjectRepository(session)
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

    def list_tasks(
        self,
        *,
        status: TaskStatus | str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        project_id: str | UUID | None = None,
        priority: TaskPriority | str | None = None,
        root_only: bool = False,
    ) -> list[Task]:
        try:
            return self.repository.list(
                status=status.value if hasattr(status, "value") else status,
                sort_by=sort_by,
                order=order,
                project_id=str(project_id) if project_id else None,
                priority=priority.value if hasattr(priority, "value") else priority,
                root_only=root_only,
            )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def list_task_views(
        self,
        *,
        status: TaskStatus | str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        project_id: str | UUID | None = None,
        priority: TaskPriority | str | None = None,
        root_only: bool = True,
        limit: int | None = None,
    ) -> list[TaskRead]:
        try:
            rows = self.repository.list_with_counts(
                status=status.value if hasattr(status, "value") else status,
                sort_by=sort_by,
                order=order,
                project_id=str(project_id) if project_id else None,
                priority=priority.value if hasattr(priority, "value") else priority,
                root_only=root_only,
                limit=limit,
            )
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return [
            TaskRead.from_task(
                task,
                subtask_count=total,
                completed_subtask_count=completed,
            )
            for task, total, completed in rows
        ]

    def get_task(self, task_id: str | UUID) -> Task:
        try:
            task = self.repository.get(str(task_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        if task is None:
            raise TaskNotFoundError()
        return task

    def get_task_or_none(self, task_id: str | UUID) -> Task | None:
        try:
            return self.repository.get(str(task_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def get_task_detail(self, task_id: str | UUID) -> TaskDetail:
        task = self.get_task(task_id)
        try:
            children = self.repository.subtasks(task.id)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        parent = self.get_task_or_none(task.parent_id) if task.parent_id else None
        return TaskDetail(
            **TaskRead.from_task(
                task,
                subtask_count=len(children),
                completed_subtask_count=sum(1 for child in children if child.status == "completed"),
            ).model_dump(),
            subtasks=[
                TaskRead.from_task(
                    child,
                    subtask_count=0,
                    completed_subtask_count=0,
                )
                for child in children
            ],
            parent=TaskRead.from_task(parent) if parent else None,
        )

    def list_subtasks(self, parent_id: str | UUID) -> list[TaskRead]:
        parent = self.get_task(parent_id)
        try:
            children = self.repository.subtasks(parent.id)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return [TaskRead.from_task(child) for child in children]

    def search_tasks(self, query: str) -> list[Task]:
        try:
            return self.repository.search_by_title(query.strip())
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def has_subtasks(self, task_id: str | UUID) -> bool:
        try:
            total, _ = self.repository.count_subtasks(str(task_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        return total > 0

    def subtask_counts(self, task_id: str | UUID) -> tuple[int, int]:
        try:
            return self.repository.count_subtasks(str(task_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def subtask_count(self, task_id: str | UUID) -> int:
        return self.subtask_counts(task_id)[0]

    def unfinished_subtask_count(self, task_id: str | UUID) -> int:
        try:
            return self.repository.unfinished_subtask_count(str(task_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _require_project(self, project_id: str | UUID | None) -> Project | None:
        if project_id is None:
            return None
        project = self.project_repository.get(str(project_id))
        if project is None:
            raise ProjectNotFoundError()
        if project.status == "archived":
            raise ProjectArchivedError()
        return project

    def create_task(self, data: TaskCreate, *, commit: bool = True) -> Task:
        project = self._require_project(data.project_id)
        task = Task(
            title=data.title,
            description=data.description,
            due_at=data.due_at,
            status=TaskStatus.pending.value,
            project_id=str(project.id) if project else None,
            parent_id=None,
            priority=data.priority.value,
            estimated_minutes=data.estimated_minutes,
            position=0,
            completed_at=None,
        )
        try:
            self.repository.add(task)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self.activities.record(
            action="task_created",
            summary=f"创建任务「{task.title}」",
            task=task,
            project=project,
        )
        self._flush(commit=commit)
        return task

    def create_subtask(
        self,
        parent_id: str | UUID,
        data: SubtaskCreate,
        *,
        commit: bool = True,
    ) -> Task:
        parent = self.get_task(parent_id)
        if parent.parent_id is not None:
            raise TaskHierarchyError("当前只支持父任务与子任务两级结构，子任务不能再拆分。")
        project = self._require_project(parent.project_id)
        task = Task(
            title=data.title,
            description=data.description,
            due_at=data.due_at,
            status=TaskStatus.pending.value,
            project_id=parent.project_id,
            parent_id=parent.id,
            priority=data.priority.value,
            estimated_minutes=data.estimated_minutes,
            position=0,
            completed_at=None,
        )
        try:
            task.position = self.repository.next_position(parent.id)
            self.repository.add(task)
            parent.updated_at = utc_now()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self.activities.record(
            action="subtask_created",
            summary=f"为「{parent.title}」新增子任务「{task.title}」",
            task=task,
            project=project,
        )
        self._flush(commit=commit)
        return task

    def _ensure_completable(self, task: Task) -> None:
        unfinished = [
            child
            for child in self.repository.subtasks(task.id)
            if child.status != TaskStatus.completed.value
        ]
        if unfinished:
            raise TaskHasUnfinishedSubtasksError(
                details={
                    "unfinished_subtasks": len(unfinished),
                    "titles": [child.title for child in unfinished[:5]],
                }
            )
        # V2.0: a task whose prerequisites are still pending cannot be completed.
        from app.services.dependency_service import DependencyService

        DependencyService(self.session).assert_can_complete(task)

    def _sync_subtask_projects(self, task: Task, project_id: str | None) -> int:
        children = self.repository.subtasks(task.id)
        for child in children:
            if child.project_id != project_id:
                child.project_id = project_id
                child.updated_at = utc_now()
        return len(children)

    def update_task(
        self,
        task_id: str | UUID,
        data: TaskUpdate,
        *,
        commit: bool = True,
    ) -> Task:
        task = self.get_task(task_id)
        fields = data.model_dump(exclude_unset=True)
        now = utc_now()
        previous_title = task.title
        previous_status = task.status

        if "project_id" in fields:
            if task.parent_id is not None:
                raise TaskHierarchyError("子任务的所属项目跟随父任务，不能单独修改。")
            project = self._require_project(fields["project_id"])
            new_project_id = str(project.id) if project else None
            if new_project_id != task.project_id:
                # V2.0: moving a task must not break existing dependency scope.
                from app.services.dependency_service import DependencyService

                DependencyService(self.session).assert_dependencies_survive(task, new_project_id)
                old_project_name = self.activities.project_name(task.project_id) or "无项目"
                task.project_id = new_project_id
                summary = (
                    f"将任务「{previous_title}」的项目从「{old_project_name}」"
                    f"改为「{project.name if project else '无项目'}」"
                )
                affected = self._sync_subtask_projects(task, new_project_id)
                if affected:
                    summary += f"，并同步 {affected} 个子任务"
                self.activities.record(
                    action="task_project_changed",
                    summary=summary,
                    task=task,
                    project_id=new_project_id,
                    field="project_id",
                    old_value=old_project_name,
                    new_value=project.name if project else "无项目",
                )

        for field in ("title", "description", "due_at", "priority", "estimated_minutes"):
            if field not in fields:
                continue
            value = fields[field]
            old_value = getattr(task, field)
            if field == "priority" and value is not None:
                value = value.value if hasattr(value, "value") else str(value)
            if old_value == value:
                continue
            setattr(task, field, value)
            self.activities.record(
                action="task_updated",
                summary=(
                    f"修改任务「{previous_title}」：{self._field_label(field)} "
                    f"{describe_value(field, old_value, self.timezone)} → "
                    f"{describe_value(field, value, self.timezone)}"
                ),
                task=task,
                field=field,
                old_value=describe_value(field, old_value, self.timezone),
                new_value=describe_value(field, value, self.timezone),
            )

        if "status" in fields:
            status = fields["status"]
            status_value = status.value if hasattr(status, "value") else str(status)
            if status_value == TaskStatus.completed.value:
                self._ensure_completable(task)
                if task.status != TaskStatus.completed.value:
                    task.status = TaskStatus.completed.value
                    task.completed_at = now
                    self.activities.record(
                        action="task_completed",
                        summary=f"完成任务「{task.title}」",
                        task=task,
                    )
                elif task.completed_at is None:
                    task.completed_at = now
            else:
                if task.status == TaskStatus.completed.value:
                    self.activities.record(
                        action="task_reopened",
                        summary=f"将任务「{task.title}」恢复为待完成",
                        task=task,
                    )
                task.status = TaskStatus.pending.value
                task.completed_at = None

        if task.status != previous_status and previous_status == TaskStatus.completed.value:
            # Reopened tasks never keep a completion timestamp.
            task.completed_at = None
        task.updated_at = now
        self._flush(commit=commit)
        return task

    @staticmethod
    def _field_label(field: str) -> str:
        return {
            "title": "标题",
            "description": "描述",
            "due_at": "截止时间",
            "priority": "优先级",
            "estimated_minutes": "预计耗时",
        }.get(field, field)

    def set_status(self, task_id: str | UUID, status: TaskStatus, *, commit: bool = True) -> Task:
        return self.update_task(task_id, TaskUpdate(status=status), commit=commit)

    def complete_task(self, task_id: str | UUID, *, commit: bool = True) -> Task:
        return self.set_status(task_id, TaskStatus.completed, commit=commit)

    def delete_task(
        self,
        task_id: str | UUID,
        *,
        confirm_subtasks: bool = False,
        commit: bool = True,
    ) -> None:
        task = self.get_task(task_id)
        children = self.repository.subtasks(task.id)
        if children and not confirm_subtasks:
            raise TaskHasSubtasksError(details={"subtask_count": len(children)})
        for child in children:
            self.activities.record(
                action="task_deleted",
                summary=f"随父任务「{task.title}」一起删除子任务「{child.title}」",
                task=child,
            )
        self.activities.record(
            action="task_deleted",
            summary=(
                f"删除任务「{task.title}」"
                + (f"，同时删除 {len(children)} 个子任务" if children else "")
            ),
            task=task,
        )
        try:
            for child in children:
                self.repository.delete(child)
            self.repository.delete(task)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=commit)

    def reorder_subtasks(
        self,
        parent_id: str | UUID,
        subtask_ids: list[UUID] | list[str],
        *,
        commit: bool = True,
    ) -> list[TaskRead]:
        parent = self.get_task(parent_id)
        children = self.repository.subtasks(parent.id)
        requested = [str(item) for item in subtask_ids]
        if sorted(requested) != sorted(child.id for child in children):
            raise InvalidSubtaskOrderError()
        by_id = {child.id: child for child in children}
        for index, child_id in enumerate(requested):
            by_id[child_id].position = index
        parent.updated_at = utc_now()
        self.activities.record(
            action="task_updated",
            summary=f"调整任务「{parent.title}」的子任务顺序",
            task=parent,
            field="subtask_order",
        )
        self._flush(commit=commit)
        return [TaskRead.from_task(by_id[child_id]) for child_id in requested]
