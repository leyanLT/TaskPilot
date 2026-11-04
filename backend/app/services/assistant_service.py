"""AI assistant orchestration, conversation persistence, and safe errors."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.graph import (
    AgentCompletedEvent,
    AgentRunner,
    AgentRunResult,
    AgentStatusEvent,
    AgentTokenEvent,
)
from app.agent.prompts import PROMPT_VERSION, build_system_prompt
from app.agent.tools import TaskToolset
from app.config import Settings
from app.database import utc_now
from app.exceptions import (
    AIAuthenticationError,
    AIInvalidOutputError,
    AINotConfiguredError,
    AIServiceUnavailableError,
    AITimeoutError,
    AIUpstreamError,
    AppError,
    AssistantCandidateMismatchError,
    AssistantMessageNotFoundError,
    DatabaseOperationError,
    PendingActionNotFoundError,
)
from app.models import AssistantMessage
from app.repositories.assistant_message_repository import AssistantMessageRepository
from app.schemas import (
    AssistantHistoryResponse,
    AssistantMessageRequest,
    AssistantTurnResponse,
    ChatMessageView,
    ChatRole,
    PendingActionView,
    TaskCandidate,
)
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService

logger = logging.getLogger("taskpilot.agent")

ModelFactory = Callable[[Settings], Any]
CONTEXT_MESSAGE_LIMIT = 12
CONTEXT_CHAR_LIMIT = 8000
HISTORY_DEFAULT_LIMIT = 50


class AssistantService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        model_factory: ModelFactory | None = None,
        narrative_writer: Callable[[str], str] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        if model_factory is None:
            from app.agent.llm import build_chat_model

            model_factory = build_chat_model
        self.model_factory = model_factory
        self.narrative_writer = narrative_writer
        self.task_service = TaskService(session, timezone=settings.timezone)
        self.action_service = PendingActionService(
            session,
            self.task_service,
            ttl_minutes=settings.pending_action_ttl_minutes,
            timezone=settings.timezone,
        )
        self.message_repository = AssistantMessageRepository(session)

    def _commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    def _ensure_configured(self) -> None:
        if not self.settings.agent_enabled:
            raise AINotConfiguredError()

    def get_history(self, limit: int = HISTORY_DEFAULT_LIMIT) -> AssistantHistoryResponse:
        safe_limit = max(1, min(limit, 100))
        records = self.message_repository.recent(safe_limit)
        return AssistantHistoryResponse(messages=[self._to_view(record) for record in records])

    def handle_message(self, request: AssistantMessageRequest) -> AssistantTurnResponse:
        self._ensure_configured()

        if request.selected_task_id is not None:
            return self._handle_selected_candidate(request)

        history = self._context_messages()
        user_record = self._save_user_message(request.message)
        try:
            result = self._build_runner().run(
                message=request.message,
                system_prompt=build_system_prompt(
                    timezone=self.settings.timezone,
                    now=datetime.now(UTC),
                ),
                history=history,
            )
        except AppError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

        assistant_record = self._save_assistant_result(result)
        return AssistantTurnResponse(
            user_message=self._to_view(user_record),
            assistant_message=self._to_view(assistant_record),
        )

    async def stream_message(
        self,
        request: AssistantMessageRequest,
    ) -> AsyncIterator[tuple[str, dict[str, object]]]:
        """Yield server-sent event names and JSON-ready payloads."""

        self._ensure_configured()
        if request.selected_task_id is not None:
            turn = self._handle_selected_candidate(request)
            yield (
                "started",
                {"user_message": turn.user_message.model_dump(mode="json")},
            )
            yield (
                "done",
                {"assistant_message": turn.assistant_message.model_dump(mode="json")},
            )
            return

        history = self._context_messages()
        user_record = self._save_user_message(request.message)
        yield (
            "started",
            {
                "user_message": self._to_view(user_record).model_dump(mode="json"),
                "prompt_version": PROMPT_VERSION,
            },
        )

        try:
            runner = self._build_runner()
            completed: AgentRunResult | None = None
            async for event in runner.astream(
                message=request.message,
                system_prompt=build_system_prompt(
                    timezone=self.settings.timezone,
                    now=datetime.now(UTC),
                ),
                history=history,
            ):
                if isinstance(event, AgentStatusEvent):
                    yield ("status", {"phase": event.phase})
                elif isinstance(event, AgentTokenEvent):
                    yield ("token", {"delta": event.delta})
                elif isinstance(event, AgentCompletedEvent):
                    completed = event.result

            if completed is None:
                raise AIInvalidOutputError()
            assistant_record = self._save_assistant_result(completed)
            yield (
                "done",
                {"assistant_message": self._to_view(assistant_record).model_dump(mode="json")},
            )
        except AppError as exc:
            yield ("error", {"error": {"code": exc.code, "message": exc.message}})
        except Exception as exc:
            mapped = self._map_error(exc)
            yield ("error", {"error": {"code": mapped.code, "message": mapped.message}})

    def _build_runner(self) -> AgentRunner:
        from app.services.activity_service import ActivityService
        from app.services.planning_service import PlanningService
        from app.services.priority_service import PriorityService
        from app.services.project_service import ProjectService
        from app.services.report_service import ReportService

        report_writer = self.narrative_writer
        if report_writer is None and self.settings.agent_enabled:
            from app.agent.narrative import build_report_narrative_writer

            report_writer = build_report_narrative_writer(self.settings)
        tools = TaskToolset(
            self.task_service,
            self.action_service,
            timezone=self.settings.timezone,
            project_service=ProjectService(self.session, timezone=self.settings.timezone),
            planning_service=PlanningService(self.session, timezone=self.settings.timezone),
            priority_service=PriorityService(self.session, timezone=self.settings.timezone),
            activity_service=ActivityService(self.session, timezone=self.settings.timezone),
            report_service=ReportService(
                self.session,
                timezone=self.settings.timezone,
                narrative_writer=report_writer,
            ),
        ).build()
        model = self.model_factory(self.settings)
        return AgentRunner(
            model,
            tools,
            recursion_limit=self.settings.agent_recursion_limit,
        )

    def _handle_selected_candidate(
        self,
        request: AssistantMessageRequest,
    ) -> AssistantTurnResponse:
        if request.selected_task_id is None:
            raise AssistantCandidateMismatchError()
        selected_id = str(request.selected_task_id)

        source: AssistantMessage | None = None
        if request.source_message_id is not None:
            source = self.message_repository.get(str(request.source_message_id))
            if source is None:
                raise AssistantMessageNotFoundError()
            candidates = self._stored_candidates(source)
            if not any(str(candidate.id) == selected_id for candidate in candidates):
                raise AssistantCandidateMismatchError()

        task = self.task_service.get_task(selected_id)
        action = self.action_service.create_completion_draft(task)
        view = self.action_service.to_view(action)
        text = f"{view.summary}。请在下方确认后执行。"
        user_record = self._save_user_message(request.message)
        if source is not None:
            self.message_repository.clear_candidates(source.id)
            self._commit()
        assistant_record = self._save_assistant_message(
            content=text,
            action_id=action.id,
        )
        return AssistantTurnResponse(
            user_message=self._to_view(user_record),
            assistant_message=self._to_view(assistant_record),
        )

    def _save_user_message(self, content: str) -> AssistantMessage:
        try:
            record = self.message_repository.add(
                role=ChatRole.user.value,
                content=content,
            )
            self._commit()
            return record
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    def _save_assistant_result(self, result: AgentRunResult) -> AssistantMessage:
        return self._save_assistant_message(
            content=result.message,
            action_id=str(result.action.id) if result.action else None,
            candidates=(
                [candidate.model_dump(mode="json") for candidate in result.candidates]
                if result.candidates
                else None
            ),
        )

    def _save_assistant_message(
        self,
        *,
        content: str,
        action_id: str | None = None,
        candidates: list[dict[str, object]] | None = None,
    ) -> AssistantMessage:
        try:
            record = self.message_repository.add(
                role=ChatRole.assistant.value,
                content=content,
                action_id=action_id,
                candidates=candidates,
                prompt_version=PROMPT_VERSION,
            )
            self._commit()
            return record
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

    def _context_messages(self) -> list[BaseMessage]:
        records = self.message_repository.recent(CONTEXT_MESSAGE_LIMIT)
        selected: list[AssistantMessage] = []
        total = 0
        for record in reversed(records):
            size = len(record.content) + 16
            if total + size > CONTEXT_CHAR_LIMIT and selected:
                break
            selected.append(record)
            total += size
        selected.reverse()

        history: list[BaseMessage] = []
        for record in selected:
            if record.role == ChatRole.user.value:
                history.append(HumanMessage(content=record.content))
            elif record.role == ChatRole.assistant.value:
                history.append(AIMessage(content=record.content))
        return history

    @staticmethod
    def _stored_candidates(record: AssistantMessage) -> list[TaskCandidate]:
        if not isinstance(record.candidates, list):
            return []
        candidates: list[TaskCandidate] = []
        for item in record.candidates:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(TaskCandidate.model_validate(item))
            except ValidationError:
                continue
        return candidates

    def _action_for_message(self, record: AssistantMessage) -> PendingActionView | None:
        if not record.action_id:
            return None
        try:
            action = self.action_service.get_action(record.action_id)
            action = self.action_service.expire_if_needed(action)
            return self.action_service.to_view(action)
        except PendingActionNotFoundError:
            return None
        except AppError:
            logger.warning("Unable to hydrate pending action %s", record.action_id)
            return None

    def _to_view(self, record: AssistantMessage) -> ChatMessageView:
        return ChatMessageView(
            id=record.id,
            role=ChatRole(record.role),
            content=record.content,
            action=self._action_for_message(record),
            candidates=self._stored_candidates(record),
            prompt_version=record.prompt_version,
            created_at=record.created_at or utc_now(),
        )

    def _map_error(self, exc: Exception) -> AppError:
        if isinstance(exc, AppError):
            return exc
        if isinstance(exc, GraphRecursionError):
            logger.warning("Agent exceeded its recursion limit")
            return AIInvalidOutputError()
        if isinstance(exc, openai.APITimeoutError):
            logger.warning("DeepSeek request timed out")
            return AITimeoutError()
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            logger.warning("DeepSeek authentication failed")
            return AIAuthenticationError()
        if isinstance(exc, (openai.APIConnectionError, openai.RateLimitError)):
            logger.warning("DeepSeek is unreachable or rate limited: %s", type(exc).__name__)
            return AIServiceUnavailableError()
        if isinstance(exc, openai.APIStatusError):
            logger.warning("DeepSeek API returned status %s", exc.status_code)
            if exc.status_code >= 500 or exc.status_code == 429:
                return AIServiceUnavailableError()
            return AIUpstreamError()
        if isinstance(exc, openai.OpenAIError):
            logger.warning("DeepSeek client error: %s", type(exc).__name__)
            return AIUpstreamError()
        if isinstance(exc, (ValidationError, ValueError)):
            logger.warning("Invalid agent output: %s", type(exc).__name__)
            return AIInvalidOutputError()
        logger.exception("Unexpected agent failure: %s", type(exc).__name__)
        return AIUpstreamError()
