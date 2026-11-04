"""Database access for persisted assistant conversation messages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssistantMessage


class AssistantMessageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        role: str,
        content: str,
        action_id: str | None = None,
        candidates: list[dict[str, object]] | None = None,
        prompt_version: str | None = None,
        created_at: datetime | None = None,
    ) -> AssistantMessage:
        message = AssistantMessage(
            role=role,
            content=content,
            action_id=action_id,
            candidates=candidates,
            prompt_version=prompt_version,
        )
        if created_at is not None:
            message.created_at = created_at
        self.session.add(message)
        self.session.flush()
        return message

    def get(self, message_id: str) -> AssistantMessage | None:
        return self.session.get(AssistantMessage, message_id)

    def recent(self, limit: int = 50) -> list[AssistantMessage]:
        statement = (
            select(AssistantMessage)
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(limit)
        )
        newest_first = list(self.session.scalars(statement))
        return list(reversed(newest_first))

    def clear_candidates(self, message_id: str) -> None:
        message = self.get(message_id)
        if message is not None:
            message.candidates = None
