"""Database access for tasks. No business rules live here."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeVar

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session, aliased

from app.models import Task

_UNSET = TypeVar("_UNSET")

SortField = Literal["created_at", "due_at", "priority", "due_date"]


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, task: Task) -> Task:
        self.session.add(task)
        self.session.flush()
        return task

    def get(self, task_id: str) -> Task | None:
        return self.session.get(Task, task_id)

    def list(
        self,
        *,
        status: str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        project_id: str | None = None,
        priority: str | None = None,
        parent_id: str | None = None,
        root_only: bool = False,
        limit: int | None = None,
    ) -> list[Task]:
        statement: Select[tuple[Task]] = select(Task)
        if status:
            statement = statement.where(Task.status == status)
        if project_id:
            statement = statement.where(Task.project_id == project_id)
        if priority:
            statement = statement.where(Task.priority == priority)
        if parent_id:
            statement = statement.where(Task.parent_id == parent_id)
        if root_only:
            statement = statement.where(Task.parent_id.is_(None))

        descending = order == "desc"
        if sort_by == "due_at":
            statement = statement.order_by(
                case((Task.due_at.is_(None), 1), else_=0),
                Task.due_at.desc() if descending else Task.due_at.asc(),
                Task.created_at.desc(),
            )
        elif sort_by == "priority":
            priority_rank = case(
                (Task.priority == "high", 0),
                (Task.priority == "medium", 1),
                else_=2,
            )
            statement = statement.order_by(
                priority_rank.desc() if descending else priority_rank.asc(),
                Task.due_at.asc(),
            )
        else:
            statement = statement.order_by(
                Task.created_at.desc() if descending else Task.created_at.asc()
            )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def list_with_counts(
        self,
        *,
        status: str | None = None,
        sort_by: str = "created_at",
        order: str = "desc",
        project_id: str | None = None,
        priority: str | None = None,
        root_only: bool = False,
        limit: int | None = None,
    ) -> list[tuple[Task, int, int]]:
        child = aliased(Task)
        total_subtasks = (
            select(func.count(child.id))
            .where(child.parent_id == Task.id)
            .correlate(Task)
            .scalar_subquery()
        )
        completed_subtasks = (
            select(func.count(child.id))
            .where(child.parent_id == Task.id, child.status == "completed")
            .correlate(Task)
            .scalar_subquery()
        )
        statement: Select[tuple[Task, int, int]] = select(
            Task,
            total_subtasks.label("subtask_count"),
            completed_subtasks.label("completed_subtask_count"),
        )
        if status:
            statement = statement.where(Task.status == status)
        if project_id:
            statement = statement.where(Task.project_id == project_id)
        if priority:
            statement = statement.where(Task.priority == priority)
        if root_only:
            statement = statement.where(Task.parent_id.is_(None))

        descending = order == "desc"
        if sort_by == "due_at":
            statement = statement.order_by(
                case((Task.due_at.is_(None), 1), else_=0),
                Task.due_at.desc() if descending else Task.due_at.asc(),
                Task.created_at.desc(),
            )
        elif sort_by == "priority":
            priority_rank = case(
                (Task.priority == "high", 0),
                (Task.priority == "medium", 1),
                else_=2,
            )
            statement = statement.order_by(
                priority_rank.desc() if descending else priority_rank.asc(),
                Task.due_at.asc(),
            )
        else:
            statement = statement.order_by(
                Task.created_at.desc() if descending else Task.created_at.asc()
            )
        if limit is not None:
            statement = statement.limit(limit)
        rows = self.session.execute(statement).all()
        return [(row[0], int(row[1]), int(row[2])) for row in rows]

    def search_by_title(
        self, query: str, *, limit: int = 20, root_only: bool = False
    ) -> list[Task]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = (
            select(Task)
            .where(Task.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Task.status.asc(), Task.due_at.asc(), Task.created_at.desc())
            .limit(limit)
        )
        if root_only:
            statement = statement.where(Task.parent_id.is_(None))
        return list(self.session.scalars(statement))

    def subtasks(self, parent_id: str) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.parent_id == parent_id)
            .order_by(Task.position.asc(), Task.created_at.asc())
        )
        return list(self.session.scalars(statement))

    def count_subtasks(self, parent_id: str) -> tuple[int, int]:
        statement = select(
            func.count(Task.id),
            func.sum(case((Task.status == "completed", 1), else_=0)),
        ).where(Task.parent_id == parent_id)
        total, completed = self.session.execute(statement).one()
        return int(total or 0), int(completed or 0)

    def has_unfinished_subtasks(self, parent_id: str) -> bool:
        statement = select(func.count(Task.id)).where(
            Task.parent_id == parent_id, Task.status != "completed"
        )
        return bool(self.session.execute(statement).scalar())

    def unfinished_subtask_count(self, parent_id: str) -> int:
        statement = select(func.count(Task.id)).where(
            Task.parent_id == parent_id, Task.status != "completed"
        )
        return int(self.session.execute(statement).scalar() or 0)

    def count_subtasks_for_parents(self, parent_ids: list[str]) -> dict[str, tuple[int, int]]:
        if not parent_ids:
            return {}
        statement = (
            select(
                Task.parent_id,
                func.count(Task.id),
                func.sum(case((Task.status == "completed", 1), else_=0)),
            )
            .where(Task.parent_id.in_(parent_ids))
            .group_by(Task.parent_id)
        )
        return {
            str(row[0]): (int(row[1] or 0), int(row[2] or 0))
            for row in self.session.execute(statement)
        }

    def next_position(self, parent_id: str) -> int:
        statement = select(func.max(Task.position)).where(Task.parent_id == parent_id)
        current = self.session.execute(statement).scalar()
        return int(current or 0) + 1

    def project_status_counts(self, project_id: str, *, now: datetime) -> tuple[int, int, int, int]:
        """Leaf task counts for a project: total, completed, pending, overdue."""

        child = aliased(Task)
        leaf = ~select(child.id).where(child.parent_id == Task.id).exists()
        statement = select(
            func.count(Task.id),
            func.sum(case((Task.status == "completed", 1), else_=0)),
            func.sum(case((Task.status == "pending", 1), else_=0)),
            func.sum(
                case(
                    (
                        (Task.status == "pending") & Task.due_at.is_not(None) & (Task.due_at < now),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(Task.project_id == project_id, leaf)
        total, completed, pending, overdue = self.session.execute(statement).one()
        return (
            int(total or 0),
            int(completed or 0),
            int(pending or 0),
            int(overdue or 0),
        )

    def status_counts(self, *, now: datetime, root_only: bool = True) -> dict[str, int]:
        statement = select(
            func.count(Task.id),
            func.sum(case((Task.status == "completed", 1), else_=0)),
            func.sum(case((Task.status == "pending", 1), else_=0)),
            func.sum(
                case(
                    (
                        (Task.status == "pending") & Task.due_at.is_not(None) & (Task.due_at < now),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        if root_only:
            statement = statement.where(Task.parent_id.is_(None))
        total, completed, pending, overdue = self.session.execute(statement).one()
        return {
            "total": int(total or 0),
            "completed": int(completed or 0),
            "pending": int(pending or 0),
            "overdue": int(overdue or 0),
        }

    def completed_between(self, start: datetime, end: datetime) -> list[Task]:
        statement = (
            select(Task)
            .where(
                Task.status == "completed",
                Task.completed_at.is_not(None),
                Task.completed_at >= start,
                Task.completed_at < end,
            )
            .order_by(Task.completed_at.asc())
        )
        return list(self.session.scalars(statement))

    def created_between(self, start: datetime, end: datetime) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.created_at >= start, Task.created_at < end)
            .order_by(Task.created_at.asc())
        )
        return list(self.session.scalars(statement))

    def delete(self, task: Task) -> None:
        self.session.delete(task)
        self.session.flush()
