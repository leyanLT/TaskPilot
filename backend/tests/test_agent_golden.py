"""Golden integration cases for every AI write operation and prompt version."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.agent.prompts import PROMPT_VERSION, build_system_prompt
from app.config import Settings
from app.schemas import AssistantMessageRequest
from app.services.assistant_service import AssistantService
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from tests.test_agent import ScriptedModel, configured_settings, make_tool_call


def _service_with_tool(
    session,
    settings: Settings,
    *,
    tool_name: str,
    tool_args: dict,
    final_text: str = "已生成待确认操作，请在界面中确认。",
) -> AssistantService:
    model = ScriptedModel(
        [
            make_tool_call(tool_name, tool_args),
            AIMessage(content=final_text),
        ]
    )
    return AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )


def test_golden_update_delete_and_batch_create_stay_pending(
    app,
    session,
    settings: Settings,
    client: TestClient,
    create_task,
) -> None:
    first = create_task(title="黄金任务 A")
    second = create_task(title="黄金任务 B")
    before = client.get("/api/tasks").json()

    update_service = _service_with_tool(
        session,
        settings,
        tool_name="prepare_update_task",
        tool_args={"query": "黄金任务 A", "new_title": "黄金任务 A 修改版"},
    )
    update_turn = update_service.handle_message(
        AssistantMessageRequest(message="把黄金任务 A 改个名字")
    )
    action = update_turn.assistant_message.action
    assert action is not None
    assert action.action_type == "update_task"
    assert client.get("/api/tasks").json() == before

    delete_service = _service_with_tool(
        session,
        settings,
        tool_name="prepare_delete_task",
        tool_args={"query": "黄金任务 B"},
    )
    delete_turn = delete_service.handle_message(AssistantMessageRequest(message="删除黄金任务 B"))
    delete_action = delete_turn.assistant_message.action
    assert delete_action is not None
    assert delete_action.action_type == "delete_task"
    assert {task["id"] for task in client.get("/api/tasks").json()} == {
        first["id"],
        second["id"],
    }

    create_service = _service_with_tool(
        session,
        settings,
        tool_name="prepare_create_tasks",
        tool_args={
            "tasks": [
                {"title": "黄金步骤一", "due_at": None},
                {"title": "黄金步骤二", "due_at": None},
            ]
        },
    )
    create_turn = create_service.handle_message(
        AssistantMessageRequest(message="把这项任务拆成两个步骤")
    )
    create_action = create_turn.assistant_message.action
    assert create_action is not None
    assert create_action.action_type == "create_tasks"
    assert len(create_action.proposed_tasks) == 2
    assert len(client.get("/api/tasks").json()) == 2


def test_golden_batch_reschedule_stays_pending(
    app,
    session,
    settings: Settings,
    client: TestClient,
    create_task,
) -> None:
    now = datetime.now(UTC)
    first = create_task(title="黄金逾期一", due_at=(now - timedelta(days=2)).isoformat())
    second = create_task(title="黄金逾期二", due_at=(now - timedelta(days=1)).isoformat())
    before = {task["id"]: task["due_at"] for task in client.get("/api/tasks").json()}

    service = _service_with_tool(
        session,
        settings,
        tool_name="prepare_batch_reschedule",
        tool_args={
            "scope": "overdue",
            "new_due_at": "2999-01-03T09:00:00+08:00",
            "search": "黄金逾期",
        },
    )
    turn = service.handle_message(AssistantMessageRequest(message="把黄金逾期任务统一改期"))
    action = turn.assistant_message.action
    assert action is not None
    assert action.action_type == "batch_reschedule"
    assert {str(task.id) for task in action.target_tasks} == {first["id"], second["id"]}
    assert {task["id"]: task["due_at"] for task in client.get("/api/tasks").json()} == before


def test_golden_agenda_uses_real_task_data(
    app,
    session,
    settings: Settings,
    create_task,
) -> None:
    create_task(title="黄金今日任务", due_at=datetime.now(UTC).isoformat())

    model = ScriptedModel(
        [
            make_tool_call("get_agenda", {"period": "today"}),
            AIMessage(content="今天先做黄金今日任务。"),
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
    )
    turn = service.handle_message(AssistantMessageRequest(message="帮我安排今天"))
    assert "黄金今日任务" in turn.assistant_message.content
    assert turn.assistant_message.action is None


def test_prompt_version_and_tool_catalog_are_stable() -> None:
    prompt = build_system_prompt(
        timezone=ZoneInfo("Asia/Shanghai"),
        now=datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
    )
    assert PROMPT_VERSION == "2026-11-v7"
    assert PROMPT_VERSION in prompt
    for tool_name in (
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
    ):
        assert tool_name in prompt
    assert "绝不能声称已经创建、完成、修改、删除或保存" in prompt
