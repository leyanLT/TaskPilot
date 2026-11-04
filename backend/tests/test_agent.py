"""Tests for the single-agent tools, LangGraph loop, and confirmation boundary."""

from __future__ import annotations

import json
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import openai
import pytest
from app.agent.tools import TaskToolset
from app.config import Settings
from app.exceptions import AIInvalidOutputError, AITimeoutError
from app.models import PendingAction
from app.schemas import (
    AssistantMessageRequest,
)
from app.services.assistant_service import AssistantService
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select


class ScriptedModel:
    """A deterministic stand-in for ChatOpenAI that supports bind_tools."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.bound_tools: list[Any] = []

    def bind_tools(self, tools: list[Any]) -> RunnableLambda:
        self.bound_tools = tools
        return RunnableLambda(self._next)

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        if not self.responses:
            raise AssertionError("scripted model ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(messages)
        return response


def make_tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def configured_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"deepseek_api_key": "test-key-not-real"})


@pytest.fixture
def toolset(
    settings: Settings,
    task_service: TaskService,
    action_service: PendingActionService,
) -> TaskToolset:
    return TaskToolset(
        task_service,
        action_service,
        timezone=ZoneInfo(settings.app_timezone),
    )


def get_tool(toolset: TaskToolset, name: str):
    return next(tool for tool in toolset.build() if tool.name == name)


def test_query_tool_reads_real_database_data(toolset, create_task) -> None:
    create_task(title="写实验报告")
    create_task(title="买牛奶")
    tool = get_tool(toolset, "query_tasks")
    payload = json.loads(tool.invoke({"status": "all", "search": None}))
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert {task["title"] for task in payload["tasks"]} == {"写实验报告", "买牛奶"}


def test_query_tool_filters_status(toolset, create_task, client: TestClient) -> None:
    pending = create_task(title="待办任务")
    completed = create_task(title="完成的任务")
    client.patch(f"/api/tasks/{completed['id']}", json={"status": "completed"})

    tool = get_tool(toolset, "query_tasks")
    payload = json.loads(tool.invoke({"status": "pending", "search": None}))
    assert payload["count"] == 1
    assert payload["tasks"][0]["id"] == pending["id"]
    assert payload["tasks"][0]["status"] == "pending"


def test_create_tool_creates_only_pending_action(toolset, task_service) -> None:
    tool = get_tool(toolset, "prepare_create_task")
    payload = json.loads(
        tool.invoke(
            {
                "title": "明天下午三点完成实验报告",
                "description": "整理数据",
                "due_at": "2026-11-04T15:00:00+08:00",
            }
        )
    )
    assert payload["ok"] is True
    assert payload["kind"] == "create_draft"
    action_payload = payload["action"]
    assert action_payload["action_type"] == "create_task"
    assert action_payload["status"] == "pending"
    assert action_payload["proposed_task"]["title"] == "明天下午三点完成实验报告"
    assert task_service.list_tasks() == []


def test_create_tool_rejects_invalid_input(toolset, task_service) -> None:
    tool = get_tool(toolset, "prepare_create_task")
    payload = json.loads(tool.invoke({"title": "   ", "due_at": None}))
    assert payload["ok"] is False
    assert payload["kind"] == "validation_error"
    assert task_service.list_tasks() == []


def test_ambiguous_completion_returns_candidates_without_action(
    toolset, task_service, client: TestClient, create_task
) -> None:
    created_one = create_task(title="实验报告（上午）")
    created_two = create_task(title="实验报告（下午）")
    tool = get_tool(toolset, "prepare_complete_task")
    payload = json.loads(tool.invoke({"query": "实验报告"}))
    assert payload["kind"] == "ambiguous"
    assert {candidate["id"] for candidate in payload["candidates"]} == {
        created_one["id"],
        created_two["id"],
    }
    assert client.get(f"/api/tasks/{created_one['id']}").json()["status"] == "pending"
    assert client.get(f"/api/tasks/{created_two['id']}").json()["status"] == "pending"


def test_unique_completion_creates_pending_action_not_write(
    toolset, task_service, create_task, client: TestClient
) -> None:
    created = create_task(title="唯一报告")
    tool = get_tool(toolset, "prepare_complete_task")
    payload = json.loads(tool.invoke({"query": "唯一报告"}))
    assert payload["kind"] == "complete_draft"
    assert payload["action"]["action_type"] == "complete_task"
    assert client.get(f"/api/tasks/{created['id']}").json()["status"] == "pending"


def test_agent_query_turn_uses_tool_results(
    app,
    client: TestClient,
    session,
    settings: Settings,
    create_task,
) -> None:
    create_task(title="查询真实任务")
    calls: dict[str, Any] = {}

    def final_answer(messages: list[BaseMessage]) -> AIMessage:
        assert isinstance(messages[-1], ToolMessage)
        payload = json.loads(messages[-1].content)
        calls["payload"] = payload
        return AIMessage(content=f"数据库中有 {payload['count']} 个任务。")

    model = ScriptedModel(
        [
            make_tool_call("query_tasks", {"status": "all", "search": None}),
            final_answer,
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    response = service.handle_message(AssistantMessageRequest(message="我有哪些任务？"))
    assert response.assistant_message.content == "数据库中有 1 个任务。"
    assert response.assistant_message.action is None
    assert calls["payload"]["tasks"][0]["title"] == "查询真实任务"
    tool_names = {tool.name for tool in model.bound_tools}
    assert {
        "query_tasks",
        "query_projects",
        "query_task_dependencies",
        "query_focus_stats",
        "analyze_task_risks",
        "prepare_replan",
        "prepare_create_project",
        "get_task_subtasks",
        "get_agenda",
        "get_priority_suggestions",
        "get_planning_context",
        "get_activity_log",
        "get_report_facts",
        "prepare_create_task",
        "prepare_create_tasks",
        "prepare_task_breakdown",
        "prepare_save_daily_plan",
        "prepare_save_report",
        "prepare_complete_task",
        "prepare_update_task",
        "prepare_delete_task",
        "prepare_batch_reschedule",
    } == tool_names


def test_agent_create_turn_requires_confirmation(
    app,
    client: TestClient,
    session,
    settings: Settings,
) -> None:
    model = ScriptedModel(
        [
            make_tool_call(
                "prepare_create_task",
                {
                    "title": "写周报",
                    "description": "本周总结",
                    "due_at": "2026-11-04T15:00:00+08:00",
                },
            ),
            AIMessage(content="任务已经创建完成。"),
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    response = service.handle_message(AssistantMessageRequest(message="明天下午三点写周报"))
    action = response.assistant_message.action
    assert action is not None
    assert action.action_type == "create_task"
    assert "确认" in response.assistant_message.content
    assert client.get("/api/tasks").json() == []

    confirmation = client.post(
        "/api/assistant/confirm",
        json={"action_id": str(action.id), "confirm": True},
    )
    assert confirmation.status_code == 200
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "写周报"
    assert tasks[0]["due_at"] == "2026-11-04T07:00:00+00:00"


def test_agent_ambiguous_turn_then_explicit_selection(
    app,
    client: TestClient,
    session,
    settings: Settings,
    create_task,
) -> None:
    first = create_task(title="实验报告 A")
    second = create_task(title="实验报告 B")
    model = ScriptedModel(
        [
            make_tool_call("prepare_complete_task", {"query": "实验报告"}),
            AIMessage(content="我随便选第一个。"),
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    response = service.handle_message(AssistantMessageRequest(message="把实验报告标记为完成"))
    ambiguous = response.assistant_message
    assert ambiguous.action is None
    assert len(ambiguous.candidates) == 2
    assert "选择" in ambiguous.content
    assert client.get(f"/api/tasks/{first['id']}").json()["status"] == "pending"
    assert client.get(f"/api/tasks/{second['id']}").json()["status"] == "pending"

    chosen = ambiguous.candidates[0]
    selection = service.handle_message(
        AssistantMessageRequest(
            message="选择这个任务",
            selected_task_id=chosen.id,
            source_message_id=ambiguous.id,
        )
    )
    selected_action = selection.assistant_message.action
    assert selected_action is not None
    confirmation = client.post(
        "/api/assistant/confirm",
        json={"action_id": str(selected_action.id), "confirm": True},
    )
    assert confirmation.status_code == 200
    assert client.get(f"/api/tasks/{chosen.id}").json()["status"] == "completed"


def test_agent_does_not_invent_confirmation_without_tool(
    app,
    session,
    settings: Settings,
    client: TestClient,
    create_task,
) -> None:
    created = create_task(title="不能被删除")
    model = ScriptedModel([AIMessage(content="删除任务「不能被删除」。请在下方确认后执行。")])
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    response = service.handle_message(AssistantMessageRequest(message="删除这个任务"))
    assert response.assistant_message.action is None
    assert "没有生成可执行" in response.assistant_message.content
    assert client.get(f"/api/tasks/{created['id']}").status_code == 200


def test_agent_invalid_output_is_mapped(
    app,
    session,
    settings: Settings,
) -> None:
    model = ScriptedModel([AIMessage(content="")])
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    with pytest.raises(AIInvalidOutputError):
        service.handle_message(AssistantMessageRequest(message="做一些事"))


def test_agent_timeout_is_mapped(
    app,
    session,
    settings: Settings,
) -> None:
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    model = ScriptedModel([timeout])
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    with pytest.raises(AITimeoutError):
        service.handle_message(AssistantMessageRequest(message="查询任务"))


def test_agent_auth_failure_is_mapped(
    app,
    session,
    settings: Settings,
) -> None:
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(401, request=request)
    auth_error = openai.AuthenticationError(
        "invalid key sk-test-secret",
        response=response,
        body=None,
    )
    model = ScriptedModel([auth_error])
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    from app.exceptions import AIAuthenticationError

    with pytest.raises(AIAuthenticationError) as exc_info:
        service.handle_message(AssistantMessageRequest(message="查询任务"))
    assert "sk-test-secret" not in exc_info.value.message


def test_agent_does_not_accept_second_side_effect_in_same_turn(
    app,
    session,
    settings: Settings,
) -> None:
    responses = [
        make_tool_call("prepare_create_task", {"title": "第一个草稿", "due_at": None}),
        make_tool_call("prepare_create_task", {"title": "第二个草稿", "due_at": None}, "call_2"),
        AIMessage(content="完成"),
    ]
    model = ScriptedModel(responses)
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    response = service.handle_message(AssistantMessageRequest(message="创建两个任务"))
    assert response.assistant_message.action is not None
    actions = session.scalars(select(PendingAction)).all()
    assert len(actions) == 1
    assert actions[0].payload["title"] == "第一个草稿"
