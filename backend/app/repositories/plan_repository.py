"""Database access for daily plans and their time blocks."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyPlan, PlanItem


class PlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_date(self, plan_date: date) -> DailyPlan | None:
        statement = select(DailyPlan).where(DailyPlan.plan_date == plan_date)
        return self.session.scalars(statement).first()

    def add(self, plan: DailyPlan) -> DailyPlan:
        self.session.add(plan)
        self.session.flush()
        return plan

    def items(self, plan_id: str) -> list[PlanItem]:
        statement = (
            select(PlanItem)
            .where(PlanItem.plan_id == plan_id)
            .order_by(PlanItem.position.asc(), PlanItem.start_at.asc())
        )
        return list(self.session.scalars(statement))

    def add_item(self, item: PlanItem) -> PlanItem:
        self.session.add(item)
        self.session.flush()
        return item

    def delete(self, plan: DailyPlan) -> None:
        self.session.delete(plan)
        self.session.flush()
