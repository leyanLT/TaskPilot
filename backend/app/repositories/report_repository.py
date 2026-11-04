"""Database access for saved reports."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Report


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, report: Report) -> Report:
        self.session.add(report)
        self.session.flush()
        return report

    def get(self, report_id: str) -> Report | None:
        return self.session.get(Report, report_id)

    def list(
        self,
        *,
        report_type: str | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[Report]:
        statement = select(Report)
        if report_type:
            statement = statement.where(Report.report_type == report_type)
        if project_id:
            statement = statement.where(Report.project_id == project_id)
        statement = statement.order_by(Report.created_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def delete(self, report: Report) -> None:
        self.session.delete(report)
        self.session.flush()
