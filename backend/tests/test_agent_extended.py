"""Extended AI tools, history, and pending-action tests for v1.2."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.agent.tools import TaskToolset
from app.config import Settings
from app.main import create_app
from app.models import PendingAction
from app.schemas import AssistantMessageRequest
from app.services.assistant_service import AssistantService
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select

from tests.conftest import make_settings
from tests.test_agent import ScriptedModel, configured_settings, make_tool_call


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


def _invoke(tool, args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(tool.invoke(args))


def test_update_tool_requires_confirmation_and_clears_due_date(
    toolset,
    task_service,
    action_service,
    client: TestClient,
    create_task,
) -> None:
    created = create_task(
        title="旧标题",
        due_at="2999-01-01T10:00:00+00:00",
    )
    tool = get_tool(toolset, "prepare_update_task")
    result = _invoke(
        tool,
        {
            "query": "旧标题",
            "new_title": "新标题",
            "new_description": None,
            "new_due_at": None,
            "clear_description": False,
            "clear_due_at": True,
        },
    )
    assert result["ok"] is True
    assert result["kind"] == "update_draft"
    assert result["action"]["action_type"] == "update_task"
    assert result["action"]["changes"]["changed_fields"] == ["due_at", "title"]
    unchanged = client.get(f"/api/tasks/{created['id']}").json()
    assert unchanged["title"] == "旧标题"
    assert unchanged["due_at"] is not None

    action = action_service.get_action(result["action"]["id"])
    confirmed = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["task"]["title"] == "新标题"
    assert body["task"]["due_at"] is None


def test_update_tool_refuses_ambiguous_match(
    toolset,
    action_service,
    create_task,
) -> None:
    create_task(title="报告 A")
    create_task(title="报告 B")
    result = _invoke(
        get_tool(toolset, "prepare_update_task"),
        {"query": "报告", "new_description": "新描述"},
    )
    assert result["kind"] == "needs_disambiguation"
    assert len(result["matches"]) == 2
    assert "action" not in result
    assert action_service.session.scalars(select(PendingAction)).all() == []


def test_delete_tool_requires_confirmation_and_is_idempotent(
    toolset,
    action_service,
    client: TestClient,
    create_task,
) -> None:
    created = create_task(title="待删除任务")
    result = _invoke(get_tool(toolset, "prepare_delete_task"), {"query": "待删除任务"})
    assert result["kind"] == "delete_draft"
    assert client.get(f"/api/tasks/{created['id']}").status_code == 200

    action_id = result["action"]["id"]
    first = client.post(
        "/api/assistant/confirm",
        json={"action_id": action_id, "confirm": True},
    )
    assert first.status_code == 200, first.text
    assert "已删除" in first.json()["message"]
    assert client.get(f"/api/tasks/{created['id']}").status_code == 404

    second = client.post(
        "/api/assistant/confirm",
        json={"action_id": action_id, "confirm": True},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"


def test_batch_reschedule_is_atomic_and_previewed(
    toolset,
    action_service,
    client: TestClient,
    create_task,
) -> None:
    now = datetime.now(UTC)
    first = create_task(title="批量一", due_at=(now - timedelta(days=1)).isoformat())
    second = create_task(title="批量二", due_at=(now - timedelta(hours=1)).isoformat())
    create_task(title="不相关任务", due_at=(now + timedelta(days=10)).isoformat())

    result = _invoke(
        get_tool(toolset, "prepare_batch_reschedule"),
        {
            "scope": "overdue",
            "new_due_at": "2999-01-02T10:00:00+08:00",
            "search": None,
        },
    )
    assert result["ok"] is True
    assert result["kind"] == "batch_reschedule_draft"
    action = result["action"]
    assert action["action_type"] == "batch_reschedule"
    assert len(action["target_tasks"]) == 2
    assert {task["id"] for task in action["target_tasks"]} == {
        first["id"],
        second["id"],
    }
    assert client.get(f"/api/tasks/{first['id']}").json()["due_at"] != "2999-01-02T02:00:00+00:00"

    confirmed = client.post(
        "/api/assistant/confirm",
        json={"action_id": action["id"], "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert len(body["affected_tasks"]) == 2
    assert {task["due_at"] for task in body["affected_tasks"]} == {"2999-01-02T02:00:00+00:00"}


def test_batch_create_creates_only_after_confirmation(
    toolset,
    client: TestClient,
) -> None:
    result = _invoke(
        get_tool(toolset, "prepare_create_tasks"),
        {
            "tasks": [
                {"title": "步骤一", "due_at": None},
                {"title": "步骤二", "description": "说明", "due_at": None},
            ]
        },
    )
    assert result["kind"] == "create_tasks_draft"
    assert len(result["action"]["proposed_tasks"]) == 2
    assert client.get("/api/tasks").json() == []

    action_id = result["action"]["id"]
    first = client.post(
        "/api/assistant/confirm",
        json={"action_id": action_id, "confirm": True},
    )
    assert first.status_code == 200, first.text
    assert len(first.json()["affected_tasks"]) == 2
    tasks = client.get("/api/tasks").json()
    assert {task["title"] for task in tasks} == {"步骤一", "步骤二"}

    repeated = client.post(
        "/api/assistant/confirm",
        json={"action_id": action_id, "confirm": True},
    )
    assert repeated.status_code == 200
    assert len(client.get("/api/tasks").json()) == 2


def test_agenda_tool_uses_real_tasks(toolset, create_task, client: TestClient) -> None:
    now = datetime.now(UTC)
    pending = create_task(title="今天要交", due_at=now.isoformat())
    completed = create_task(title="今天已完成")
    client.patch(f"/api/tasks/{completed['id']}", json={"status": "completed"})
    result = _invoke(get_tool(toolset, "get_agenda"), {"period": "today"})
    assert result["ok"] is True
    assert result["kind"] == "agenda"
    assert result["counts"]["due_today"] >= 1
    assert pending["title"] in {task["title"] for task in result["due_today"]}
    assert completed["title"] in {task["title"] for task in result["completed"]}


def test_conversation_history_and_multi_turn_context(
    app,
    client: TestClient,
    session,
    settings: Settings,
) -> None:
    calls: list[list[BaseMessage]] = []

    def final_answer(messages: list[BaseMessage]) -> AIMessage:
        calls.append(list(messages))
        return AIMessage(content="第一轮回复")

    second_context: list[BaseMessage] = []

    def second_answer(messages: list[BaseMessage]) -> AIMessage:
        second_context.extend(messages)
        return AIMessage(content="第二轮回复")

    model = ScriptedModel(
        [
            make_tool_call("query_tasks", {"status": "all", "search": None}),
            final_answer,
            second_answer,
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    first = service.handle_message(AssistantMessageRequest(message="第一轮问题"))
    assert first.assistant_message.content == "第一轮回复"
    second = service.handle_message(AssistantMessageRequest(message="第二轮问题"))
    assert second.assistant_message.content == "第二轮回复"

    assert any(isinstance(m, HumanMessage) and m.content == "第一轮问题" for m in second_context)
    assert any(isinstance(m, AIMessage) and m.content == "第一轮回复" for m in second_context)

    history = client.get("/api/assistant/history").json()["messages"]
    assert [item["role"] for item in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert history[0]["content"] == "第一轮问题"
    assert history[3]["content"] == "第二轮回复"
    assert history[1]["prompt_version"] == "2026-11-v7"


def test_history_hydrates_pending_action_and_candidates(
    app,
    client: TestClient,
    session,
    settings: Settings,
    create_task,
) -> None:
    create_task(title="实验报告 A")
    create_task(title="实验报告 B")
    model = ScriptedModel(
        [
            make_tool_call("prepare_complete_task", {"query": "实验报告"}),
            AIMessage(content="请选择一个任务。"),
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    service.handle_message(AssistantMessageRequest(message="完成实验报告"))
    history = client.get("/api/assistant/history").json()["messages"]
    assistant = history[-1]
    assert len(assistant["candidates"]) == 2
    assert assistant["action"] is None

    choice = assistant["candidates"][0]
    selected = service.handle_message(
        AssistantMessageRequest(
            message="选择第一个",
            selected_task_id=choice["id"],
            source_message_id=assistant["id"],
        )
    )
    assert selected.assistant_message.action is not None
    refreshed = client.get("/api/assistant/history").json()["messages"]
    assert refreshed[-2]["candidates"] == []
    assert refreshed[-1]["action"]["status"] == "pending"


def test_conversation_survives_application_restart(
    database_path,
    tmp_path,
) -> None:
    settings = make_settings(database_path, api_key="test-key-not-real")
    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        first_client.get("/api/tasks")
        session = first_app.state.session_factory()
        model = ScriptedModel([AIMessage(content="重启前的回复")])
        service = AssistantService(
            session,
            settings,
            model_factory=lambda _: model,
        )
        service.handle_message(AssistantMessageRequest(message="重启前的问题"))
        session.close()

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        history = second_client.get("/api/assistant/history").json()["messages"]
        assert [item["content"] for item in history] == ["重启前的问题", "重启前的回复"]


def test_agent_visible_history_is_bounded(
    app,
    session,
    settings: Settings,
) -> None:
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: ScriptedModel([]),
    )
    for index in range(15):
        service._save_user_message(f"旧消息 {index}")
    context = service._context_messages()
    assert len(context) <= 12
    assert all(isinstance(message, HumanMessage) for message in context)
