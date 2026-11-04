"""SSE streaming tests with a deterministic LangChain chat model."""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.config import Settings
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from tests.test_agent import make_tool_call


class StreamingScriptedModel(BaseChatModel):
    """A callback-aware chat model that streams text and emits tool calls."""

    responses: list[Any]
    index: int = 0
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "taskpilot-stream-test"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> StreamingScriptedModel:
        self.bound_tools = list(tools)
        return self

    def _next_response(self, messages: list[BaseMessage]) -> AIMessage:
        if self.index >= len(self.responses):
            raise AssertionError("scripted streaming model ran out of responses")
        response = self.responses[self.index]
        self.index += 1
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(messages)
        if not isinstance(response, AIMessage):
            raise AssertionError("scripted response must be an AIMessage")
        return response

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next_response(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        response = self._next_response(messages)
        if response.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=response.tool_calls)
            )
            return
        content = response.content if isinstance(response.content, str) else ""
        for character in content:
            if run_manager is not None:
                run_manager.on_llm_new_token(character)
            yield ChatGenerationChunk(message=AIMessageChunk(content=character))


def _sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data += line.removeprefix("data: ")
        if event_name:
            events.append((event_name, json.loads(data)))
    return events


@pytest.fixture
def configured_client(database_path):
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        database_auto_migrate=False,
        deepseek_api_key="test-key-not-real",
        app_timezone="Asia/Shanghai",
        agent_timeout_seconds=5,
        agent_max_retries=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_stream_emits_tokens_for_read_only_turn(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StreamingScriptedModel(
        responses=[
            make_tool_call("query_tasks", {"status": "all", "search": None}),
            AIMessage(content="目前没有任务。"),
        ]
    )
    monkeypatch.setattr("app.agent.llm.build_chat_model", lambda settings: model)
    configured_client.post("/api/tasks", json={"title": "真实任务"})

    response = configured_client.post(
        "/api/assistant/messages/stream",
        json={"message": "我有哪些任务？"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "started"
    assert "status" in names
    assert "token" in names
    assert names[-1] == "done"
    tokens = "".join(data["delta"] for name, data in events if name == "token")
    assert "目前没有任务。" in tokens
    done = next(data for name, data in events if name == "done")
    assert done["assistant_message"]["content"] == "目前没有任务。"
    history = configured_client.get("/api/assistant/history").json()["messages"]
    assert [item["role"] for item in history] == ["user", "assistant"]


def test_stream_does_not_leak_model_prose_for_write_turn(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StreamingScriptedModel(
        responses=[
            make_tool_call(
                "prepare_create_task",
                {"title": "写周报", "description": None, "due_at": None},
            ),
            AIMessage(content="任务已经创建完成了，你可以放心。"),
        ]
    )
    monkeypatch.setattr("app.agent.llm.build_chat_model", lambda settings: model)

    response = configured_client.post(
        "/api/assistant/messages/stream",
        json={"message": "帮我创建写周报"},
    )
    assert response.status_code == 200
    events = _sse_events(response.text)
    assert not any(name == "token" for name, _ in events)
    done = next(data for name, data in events if name == "done")
    assistant = done["assistant_message"]
    assert assistant["action"]["action_type"] == "create_task"
    assert "确认" in assistant["content"]
    assert "放心" not in response.text
    assert configured_client.get("/api/tasks").json() == []


def test_stream_returns_safe_error_event(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StreamingScriptedModel(responses=[AIMessage(content=""), RuntimeError("secret-stack")])

    def failing_model(settings: Settings):
        model.responses = [RuntimeError("secret-stack")]
        model.index = 0
        return model

    monkeypatch.setattr("app.agent.llm.build_chat_model", failing_model)
    response = configured_client.post(
        "/api/assistant/messages/stream",
        json={"message": "查询任务"},
    )
    assert response.status_code == 200
    events = _sse_events(response.text)
    assert any(name == "error" for name, _ in events)
    assert "secret-stack" not in response.text
    assert "Traceback" not in response.text
    history = configured_client.get("/api/assistant/history").json()["messages"]
    assert [item["role"] for item in history] == ["user"]
