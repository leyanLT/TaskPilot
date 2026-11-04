"""Task dependency rules: scope, cycles, blocking and completion guards."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    DependencyCycleError,
    DependencyDuplicateError,
    DependencyScopeError,
    DependencySelfError,
    TaskBlockedError,
    TaskNotFoundError,
)
from app.models import Task, TaskDependency
from app.repositories.v2_repository import TaskDependencyRepository


class DependencyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = TaskDependencyRepository(session)

    # -- helpers ---------------------------------------------------------

    def _load(self, task_id: str) -> Task:
        task = self.session.get(Task, task_id)
        if task is None:
            raise TaskNotFoundError()
        return task

    def _flush(self, *, commit: bool) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    @staticmethod
    def _same_scope(first: Task, second: Task) -> bool:
        return first.project_id == second.project_id

    def _assert_scope(self, task: Task, dependency: Task) -> None:
        if task.parent_id == dependency.id or dependency.parent_id == task.id:
            raise DependencyScopeError("父任务和子任务之间不能建立依赖关系。")
        if not self._same_scope(task, dependency):
            raise DependencyScopeError()

    def _would_cycle(self, task_id: str, depends_on_task_id: str) -> bool:
        """True when ``depends_on_task_id`` already depends on ``task_id``."""

        edges: dict[str, list[str]] = {}
        for current, target in self.repository.all_pairs():
            edges.setdefault(current, []).append(target)
        seen: set[str] = set()
        stack = [depends_on_task_id]
        while stack:
            node = stack.pop()
            if node == task_id:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(edges.get(node, ()))
        return False

    # -- writes ----------------------------------------------------------

    def add(self, task_id: str, depends_on_task_id: str) -> TaskDependency:
        if task_id == depends_on_task_id:
            raise DependencySelfError()
        task = self._load(task_id)
        dependency = self._load(depends_on_task_id)
        self._assert_scope(task, dependency)
        if self.repository.between(task_id, depends_on_task_id) is not None:
            raise DependencyDuplicateError()
        if self._would_cycle(task_id, depends_on_task_id):
            raise DependencyCycleError()
        row = TaskDependency(
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            created_at=utc_now(),
        )
        try:
            self.repository.add(row)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=True)
        return row

    def remove(self, task_id: str, dependency_id: str, *, commit: bool = True) -> None:
        row = self.repository.get(dependency_id)
        if row is None or row.task_id != task_id:
            raise TaskNotFoundError("依赖关系不存在。")
        try:
            self.repository.delete(row)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        self._flush(commit=commit)

    # -- reads -----------------------------------------------------------

    def _view(self, row: TaskDependency) -> dict[str, object]:
        other_id = row.depends_on_task_id if row.task_id == row.task_id else row.depends_on_task_id
        other = self.session.get(Task, other_id)
        return {
            "id": row.id,
            "task_id": row.task_id,
            "depends_on_task_id": row.depends_on_task_id,
            "depends_on_title": other.title if other else "（已删除的任务）",
            "depends_on_status": other.status if other else "completed",
            "created_at": row.created_at,
        }

    def for_task(self, task_id: str) -> dict[str, object]:
        task = self._load(task_id)
        depends_on_rows = self.repository.for_task(task_id)
        blocks_rows = self.repository.depending_on(task_id)
        depends_on = [self._view(row) for row in depends_on_rows]
        blocks = []
        for row in blocks_rows:
            blocks.append(
                {
                    "id": row.id,
                    "task_id": row.task_id,
                    "depends_on_task_id": row.depends_on_task_id,
                    "depends_on_title": task.title,
                    "depends_on_status": task.status,
                    "created_at": row.created_at,
                }
            )
        is_blocked = any(item["depends_on_status"] != "completed" for item in depends_on)
        return {
            "task_id": task_id,
            "is_blocked": is_blocked,
            "depends_on": depends_on,
            "blocks": blocks,
        }

    def blocked_titles(self, task_ids: list[str]) -> dict[str, list[str]]:
        """Map task id -> titles of its still-pending prerequisites."""

        if not task_ids:
            return {}
        stmt = (
            select(TaskDependency.task_id, Task.title)
            .join(Task, Task.id == TaskDependency.depends_on_task_id)
            .where(
                TaskDependency.task_id.in_(task_ids),
                Task.status != "completed",
            )
        )
        result: dict[str, list[str]] = {}
        for task_id, title in self.session.execute(stmt):
            result.setdefault(task_id, []).append(title)
        return result

    def blocked_map(self, task_ids: list[str]) -> dict[str, list[str]]:
        return self.blocked_titles(task_ids)

    def blocked_summary(self, task_ids: list[str] | None = None) -> dict[str, list[str]]:
        """Pending tasks (or the given ids) mapped to unmet prerequisite titles."""

        if task_ids is None:
            task_ids = list(self.session.scalars(select(Task.id).where(Task.status == "pending")))
        return self.blocked_titles(task_ids)

    # -- guards used by other services / agent confirmation ---------------

    def assert_can_complete(self, task: Task) -> None:
        unmet = self.blocked_titles([task.id]).get(task.id, [])
        if unmet:
            raise TaskBlockedError(
                f"「{task.title}」还在等前置任务：{'、'.join(unmet)}。",
                details={"blocked_by": unmet, "task_id": task.id},
            )

    def assert_dependencies_survive(self, task: Task, new_project_id: str | None) -> None:
        """Reject a project move that would leave cross-project dependencies."""

        rows = self.repository.for_task(task.id) + self.repository.depending_on(task.id)
        for row in rows:
            other_id = row.depends_on_task_id if row.task_id == task.id else row.task_id
            other = self.session.get(Task, other_id)
            if other is None:
                continue
            if other.project_id != new_project_id:
                raise DependencyScopeError(
                    "移动任务会让已有的依赖跨越不同项目，请先解除相关依赖。",
                    details={"dependency_id": row.id, "other_task_id": other_id},
                )
