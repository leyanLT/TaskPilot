"""V1.5 agent tools: breakdown, daily planning, priorities, activities, reports.

All model calls are scripted; no network or real API key is used.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.schemas import AssistantMessageRequest
from app.services.assistant_service import AssistantService
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from tests.test_agent import ScriptedModel, configured_settings, make_tool_call

TIMEZONE = ZoneInfo("Asia/Shanghai")


def today_local():
    return datetime.now(TIMEZONE).date()


def at_local(plan_date, hour: int, minute: int = 0) -> str:
    return datetime.combine(plan_date, time(hour, minute), tzinfo=TIMEZONE).isoformat()


def service_with_tool(
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


def confirm(client: TestClient, action_id: str, overrides: dict | None = None) -> dict:
    body: dict[str, object] = {"action_id": action_id, "confirm": True}
    if overrides is not None:
        body["payload_overrides"] = overrides
    response = client.post("/api/assistant/confirm", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_breakdown_draft_stays_pending_then_creates_hierarchy(
    session, settings: Settings, client: TestClient
) -> None:
    project = client.post("/api/projects", json={"name": "Agent 项目", "status": "active"}).json()
    service = service_with_tool(
        session,
        settings,
        tool_name="prepare_task_breakdown",
        tool_args={
            "goal": "两周内完成 AI Agent 项目",
            "project_id": project["id"],
            "tasks": [
                {
                    "title": "设计 Agent 架构",
                    "description": "确定工具与状态",
                    "priority": "high",
                    "estimated_minutes": 120,
                    "due_at": "2999-01-01T18:00:00+08:00",
                    "subtasks": [
                        {"title": "列出工具清单", "estimated_minutes": 30},
                        {"title": "画流程图", "estimated_minutes": 45},
                    ],
                },
                {
                    "title": "实现工具调用",
                    "priority": "medium",
                    "estimated_minutes": 180,
                    "subtasks": [],
                },
            ],
        },
    )
    turn = service.handle_message(AssistantMessageRequest(message="帮我把 AI Agent 项目拆解成任务"))
    action = turn.assistant_message.action
    assert action is not None
    assert action.action_type == "create_task_breakdown"
    assert action.proposed_breakdown is not None
    assert action.proposed_breakdown.project_name == "Agent 项目"
    assert [task.title for task in action.proposed_breakdown.tasks] == [
        "设计 Agent 架构",
        "实现工具调用",
    ]
    assert client.get("/api/tasks").json() == []

    created = confirm(client, str(action.id))
    assert created["status"] == "confirmed"
    assert len(created["affected_tasks"]) == 4

    tasks = client.get("/api/tasks").json()
    assert {task["title"] for task in tasks} == {"设计 Agent 架构", "实现工具调用"}
    assert all(task["project_id"] == project["id"] for task in tasks)
    parent = next(task for task in tasks if task["title"] == "设计 Agent 架构")
    assert parent["priority"] == "high"
    assert parent["subtask_count"] == 2

    detail = client.get(f"/api/tasks/{parent['id']}").json()
    assert {item["title"] for item in detail["subtasks"]} == {
        "列出工具清单",
        "画流程图",
    }

    replay = confirm(client, str(action.id))
    assert replay["status"] == "confirmed"
    assert len(client.get("/api/tasks").json()) == 2


def test_breakdown_overrides_apply_before_confirmation(
    session, settings: Settings, client: TestClient
) -> None:
    service = service_with_tool(
        session,
        settings,
        tool_name="prepare_task_breakdown",
        tool_args={
            "goal": "写一份方案",
            "tasks": [
                {"title": "原始任务一", "subtasks": []},
                {"title": "原始任务二", "subtasks": []},
            ],
        },
    )
    turn = service.handle_message(AssistantMessageRequest(message="拆解写方案"))
    action = turn.assistant_message.action
    assert action is not None and action.proposed_breakdown is not None

    overrides = {
        "goal": action.proposed_breakdown.goal,
        "project_id": None,
        "tasks": [
            {"title": "编辑后的任务", "priority": "high", "subtasks": []},
        ],
    }
    result = confirm(client, str(action.id), overrides=overrides)
    assert result["status"] == "confirmed"
    tasks = client.get("/api/tasks").json()
    assert [task["title"] for task in tasks] == ["编辑后的任务"]


def test_invalid_override_does_not_consume_the_action(
    session, settings: Settings, client: TestClient
) -> None:
    service = service_with_tool(
        session,
        settings,
        tool_name="prepare_task_breakdown",
        tool_args={
            "goal": "写一份方案",
            "tasks": [{"title": "保留原任务", "subtasks": []}],
        },
    )
    turn = service.handle_message(AssistantMessageRequest(message="拆解写方案"))
    action = turn.assistant_message.action
    assert action is not None

    invalid = client.post(
        "/api/assistant/confirm",
        json={
            "action_id": str(action.id),
            "confirm": True,
            "payload_overrides": {"goal": "x", "tasks": []},
        },
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "ACTION_CONFLICT"
    assert client.get("/api/tasks").json() == []

    # The action is still pending, so a valid confirmation still works.
    result = confirm(client, str(action.id))
    assert result["status"] == "confirmed"
    assert [task["title"] for task in client.get("/api/tasks").json()] == ["保留原任务"]


def test_breakdown_tool_reports_schedule_warnings(
    task_service, action_service, client: TestClient
) -> None:
    project = client.post(
        "/api/projects",
        json={
            "name": "已过期项目",
            "status": "active",
            "start_date": "2026-01-01",
            "due_date": "2026-01-02",
        },
    ).json()
    from app.agent.tools import TaskToolset

    toolset = TaskToolset(task_service, action_service, timezone=TIMEZONE)
    tool = next(item for item in toolset.build() if item.name == "prepare_task_breakdown")
    payload = json.loads(
        tool.invoke(
            {
                "goal": "赶工",
                "project_id": project["id"],
                "tasks": [
                    {
                        "title": "晚于项目截止的任务",
                        "due_at": "2999-01-01T10:00:00+08:00",
                        "estimated_minutes": 600,
                        "subtasks": [],
                    }
                ],
            }
        )
    )
    assert payload["ok"] is True
    assert payload["kind"] == "breakdown_draft"
    warnings = payload["warnings"]
    assert any("项目截止日期已经过去" in warning for warning in warnings)
    assert any("晚于项目截止日期" in warning for warning in warnings)
    assert any("可能不可行" in warning for warning in warnings)


def test_priority_tool_explains_real_factors(
    task_service, action_service, client: TestClient
) -> None:
    client.post(
        "/api/tasks",
        json={
            "title": "紧急任务",
            "priority": "high",
            "due_at": (datetime.now(TIMEZONE) - timedelta(hours=2)).isoformat(),
        },
    )
    client.post(
        "/api/tasks",
        json={"title": "普通任务", "priority": "low"},
    )
    from app.agent.tools import TaskToolset

    toolset = TaskToolset(task_service, action_service, timezone=TIMEZONE)
    tool = next(item for item in toolset.build() if item.name == "get_priority_suggestions")
    payload = json.loads(tool.invoke({"limit": 5, "project_id": None}))
    assert payload["ok"] is True
    first = payload["suggestions"][0]
    assert first["title"] == "紧急任务"
    assert first["suggested_priority"] == "high"
    assert any("逾期" in reason for reason in first["reasons"])
    assert payload["suggestions"][1]["title"] == "普通任务"


def test_daily_plan_draft_and_confirmation(session, settings: Settings, client: TestClient) -> None:
    plan_date = today_local()
    first = client.post(
        "/api/tasks",
        json={"title": "计划任务一", "estimated_minutes": 60, "priority": "high"},
    ).json()
    second = client.post(
        "/api/tasks",
        json={"title": "计划任务二", "estimated_minutes": 30},
    ).json()

    service = service_with_tool(
        session,
        settings,
        tool_name="prepare_save_daily_plan",
        tool_args={
            "plan_date": plan_date.isoformat(),
            "available_minutes": 180,
            "items": [
                {
                    "task_id": first["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                    "note": "先做重要任务",
                },
                {
                    "task_id": second["id"],
                    "start_at": at_local(plan_date, 10, 30),
                    "end_at": at_local(plan_date, 11),
                    "note": None,
                },
            ],
        },
    )
    turn = service.handle_message(
        AssistantMessageRequest(message="我今天有 3 小时，帮我安排今天的任务")
    )
    action = turn.assistant_message.action
    assert action is not None
    assert action.action_type == "save_daily_plan"
    assert action.proposed_plan is not None
    assert client.get(f"/api/plans/{plan_date.isoformat()}").status_code == 404

    saved = confirm(client, str(action.id))
    assert saved["plan_date"] == plan_date.isoformat()
    plan = client.get(f"/api/plans/{plan_date.isoformat()}").json()
    assert plan["planned_minutes"] == 90
    assert [item["task_title"] for item in plan["items"]] == ["计划任务一", "计划任务二"]

    replay = confirm(client, str(action.id))
    assert replay["plan_date"] == plan_date.isoformat()
    assert len(client.get(f"/api/plans/{plan_date.isoformat()}").json()["items"]) == 2


def test_daily_plan_tool_rejects_over_capacity(
    session, settings: Settings, client: TestClient
) -> None:
    plan_date = today_local()
    task = client.post("/api/tasks", json={"title": "大任务", "estimated_minutes": 120}).json()
    service = service_with_tool(
        session,
        settings,
        tool_name="prepare_save_daily_plan",
        tool_args={
            "plan_date": plan_date.isoformat(),
            "available_minutes": 60,
            "items": [
                {
                    "task_id": task["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 11),
                    "note": None,
                }
            ],
        },
    )
    turn = service.handle_message(AssistantMessageRequest(message="安排今天"))
    assert "超过可用时间" in turn.assistant_message.content
    assert turn.assistant_message.action is None
    assert client.get(f"/api/plans/{plan_date.isoformat()}").status_code == 404


def test_report_tool_saves_only_after_confirmation(
    session, settings: Settings, client: TestClient
) -> None:
    task = client.post("/api/tasks", json={"title": "报告任务"}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})

    model = ScriptedModel(
        [
            make_tool_call(
                "prepare_save_report",
                {
                    "report_type": "daily",
                    "period_start": None,
                    "period_end": None,
                    "project_id": None,
                },
            ),
            AIMessage(content="已生成待确认操作，请在界面中确认。"),
        ]
    )
    service = AssistantService(
        session,
        configured_settings(settings),
        model_factory=lambda _: model,
        narrative_writer=lambda prompt: (
            "存在的问题：\n- 任务集中在少数项目\n后续建议：\n- 保持每日节奏"
        ),
    )
    turn = service.handle_message(AssistantMessageRequest(message="帮我生成今天的工作日报"))
    action = turn.assistant_message.action
    assert action is not None
    assert action.action_type == "save_report"
    assert action.proposed_report is not None
    assert "统计范围" in action.proposed_report.content_md
    assert client.get("/api/reports").json() == []

    saved = confirm(client, str(action.id))
    assert saved["report_id"]
    report = client.get(f"/api/reports/{saved['report_id']}").json()
    assert "报告任务" in report["content_md"]
    assert report["facts"]["counts"]["completed"] >= 1

    replay = confirm(client, str(action.id))
    assert replay["report_id"] == saved["report_id"]
    assert len(client.get("/api/reports").json()) == 1


def test_report_facts_tool_uses_backend_statistics(
    task_service, action_service, client: TestClient
) -> None:
    task = client.post("/api/tasks", json={"title": "统计任务"}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    from app.agent.tools import TaskToolset

    toolset = TaskToolset(task_service, action_service, timezone=TIMEZONE)
    tool = next(item for item in toolset.build() if item.name == "get_report_facts")
    payload = json.loads(
        tool.invoke(
            {
                "report_type": "daily",
                "period_start": None,
                "period_end": None,
                "project_id": None,
            }
        )
    )
    assert payload["ok"] is True
    assert payload["kind"] == "report_facts"
    assert payload["counts"]["completed"] >= 1
    assert "统计任务" in payload["completed_tasks"]


def test_report_tool_normalizes_same_day_and_one_sided_periods(
    task_service, action_service, client: TestClient
) -> None:
    """Real models often send YYYY-MM-DD for both ends; that must mean one day."""

    from app.agent.tools import TaskToolset

    today = datetime.now(TIMEZONE).date().isoformat()
    next_day = (datetime.now(TIMEZONE).date() + timedelta(days=1)).isoformat()
    client.post("/api/tasks", json={"title": "范围内任务"})
    toolset = TaskToolset(task_service, action_service, timezone=TIMEZONE)

    facts_tool = next(item for item in toolset.build() if item.name == "get_report_facts")
    same_day = json.loads(
        facts_tool.invoke(
            {
                "report_type": "daily",
                "period_start": today,
                "period_end": today,
                "project_id": None,
            }
        )
    )
    assert same_day["ok"] is True, same_day
    assert same_day["kind"] == "report_facts"
    assert same_day["period_start_local"].startswith(today)
    assert same_day["period_end_local"].startswith(next_day)

    one_sided = json.loads(
        facts_tool.invoke(
            {
                "report_type": "daily",
                "period_start": today,
                "period_end": None,
                "project_id": None,
            }
        )
    )
    assert one_sided["ok"] is True, one_sided

    prepare_tool = next(item for item in toolset.build() if item.name == "prepare_save_report")
    prepared = json.loads(
        prepare_tool.invoke(
            {
                "report_type": "daily",
                "period_start": today,
                "period_end": today,
                "project_id": None,
            }
        )
    )
    assert prepared["ok"] is True, prepared
    assert prepared["kind"] == "report_draft"
    report = prepared["action"]["proposed_report"]
    assert report["period_start"] != report["period_end"]
