"""Database access for server-side pending assistant actions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import PendingAction


class PendingActionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, action: PendingAction) -> PendingAction:
        self.session.add(action)
        self.session.flush()
        return action

    def get(self, action_id: str) -> PendingAction | None:
        return self.session.get(PendingAction, action_id)

    def claim_for_confirmation(self, action_id: str, now: datetime) -> bool:
        """Atomically move a live pending action into the processing state.

        The row-level conditional update prevents two concurrent confirms from
        executing the underlying task write twice.
        """

        statement = (
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == "pending",
                PendingAction.expires_at > now,
            )
            .values(status="processing", resolved_at=None)
            .execution_options(synchronize_session="fetch")
        )
        result = self.session.execute(statement)
        return result.rowcount == 1

    def claim_for_cancellation(self, action_id: str) -> bool:
        statement = (
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == "pending",
            )
            .values(status="cancelled")
            .execution_options(synchronize_session="fetch")
        )
        result = self.session.execute(statement)
        return result.rowcount == 1

    def mark_confirmed(self, action_id: str, *, result_task_id: str | None, now: datetime) -> bool:
        statement = (
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == "processing",
            )
            .values(status="confirmed", result_task_id=result_task_id, resolved_at=now)
            .execution_options(synchronize_session="fetch")
        )
        result = self.session.execute(statement)
        return result.rowcount == 1

    def mark_expired(self, action_id: str, *, now: datetime) -> bool:
        statement = (
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == "pending",
                PendingAction.expires_at <= now,
            )
            .values(status="expired", resolved_at=now)
            .execution_options(synchronize_session="fetch")
        )
        result = self.session.execute(statement)
        return result.rowcount == 1
