"""Database access for projects. No business rules live here."""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: Project) -> Project:
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    def find_by_name(self, name: str) -> list[Project]:
        escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = (
            select(Project)
            .where(Project.name.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Project.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def list(
        self,
        *,
        status: str | None = None,
        include_archived: bool = True,
        search: str | None = None,
    ) -> list[Project]:
        statement: Select[tuple[Project]] = select(Project)
        if status:
            statement = statement.where(Project.status == status)
        elif not include_archived:
            statement = statement.where(Project.status != "archived")
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(Project.name.ilike(f"%{escaped}%", escape="\\"))
        statement = statement.order_by(Project.created_at.desc())
        return list(self.session.scalars(statement))

    def delete(self, project: Project) -> None:
        self.session.delete(project)
        self.session.flush()
