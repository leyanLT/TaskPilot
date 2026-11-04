"""V2.0 F05/F08: agent tools and the confirmed replan write path."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.agent.graph import ACTION_KINDS
from app.agent.tools import TaskToolset
from app.exceptions import PlanVersionConflictError
from app.models import PlanRevision
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

TZ = ZoneInfo("Asia/Shanghai")


def local_iso(day: date, hour: int) -> str:
    return datetime.combine(day, time(hour, 0), tzinfo=TZ).isoformat()


def _tools(task_service: TaskService, action_service: PendingActionService):
    toolset = TaskToolset(
        task_service,
        action_service,
        timezone=TZ,
    )
    return {tool.name: tool for tool in toolset.build()}


def test_query_task_dependencies_tool(
    client: TestClient,
    session: Session,
    task_service: TaskService,
    action_service: PendingActionService,
    create_task: Callable[..., dict],
) -> None:
    prerequisite = create_task(title="先做实验")
    dependent = create_task(title="写实验分析")
    client.post(
        f"/api/dependencies/{dependent['id']}",
        json={"depends_on_task_id": prerequisite["id"]},
    )

    tools = _tools(task_service, action_service)
    payload = json.loads(tools["query_task_dependencies"].invoke({"query": "写实验分析"}))
    assert payload["ok"] is True
    assert payload["is_blocked"] is True
    assert payload["depends_on"][0]["depends_on_title"] == "先做实验"
    assert "阻塞" in payload["message"]

    missing = json.loads(tools["query_task_dependencies"].invoke({"query": "不存在的任务"}))
    assert missing["kind"] == "not_found"


def test_query_focus_stats_and_risk_tools(
    client: TestClient,
    session: Session,
    task_service: TaskService,
    action_service: PendingActionService,
    create_task: Callable[..., dict],
) -> None:
    overdue = create_task(
        title="逾期实验报告",
        due_at=(datetime.now(TZ) - timedelta(days=2)).isoformat(),
    )
    focus_task = create_task(title="专注任务")
    started = client.post(
        "/api/focus/start", json={"task_id": focus_task["id"], "planned_minutes": 25}
    ).json()
    client.post(f"/api/focus/{started['id']}/stop")

    tools = _tools(task_service, action_service)
    stats = json.loads(tools["query_focus_stats"].invoke({}))
    assert stats["ok"] is True
    assert stats["sessions"] >= 1
    assert stats["today_minutes"] >= 0

    risks = json.loads(tools["analyze_task_risks"].invoke({}))
    assert risks["ok"] is True
    codes = {item["code"] for item in risks["items"]}
    assert "TASK_OVERDUE" in codes
    overdue_item = next(item for item in risks["items"] if item["code"] == "TASK_OVERDUE")
    assert overdue["id"] in overdue_item["task_ids"]
    assert risks["message"]


def test_prepare_replan_confirms_and_is_idempotent(
    client: TestClient,
    session: Session,
    task_service: TaskService,
    action_service: PendingActionService,
    create_task: Callable[..., dict],
) -> None:
    day = date.today() + timedelta(days=1)
    create_task(title="写第一章", estimated_minutes=60)
    create_task(title="整理数据", estimated_minutes=45)

    tools = _tools(task_service, action_service)
    raw = json.loads(
        tools["prepare_replan"].invoke({"plan_date": day.isoformat(), "reason": "今天的实验没做完"})
    )
    assert raw["ok"] is True
    assert raw["kind"] == "replan_draft"
    assert "replan_draft" in ACTION_KINDS
    action_id = raw["action"]["id"]
    assert len(raw["action"]["proposed_replan"]["after"]) >= 1
    assert raw["explanation"]

    # The tool must not write anything before confirmation.
    assert client.get(f"/api/plans/{day.isoformat()}").status_code == 404

    confirmed = action_service.confirm(action_id, confirm=True)
    assert confirmed.status.value == "confirmed"
    assert confirmed.plan_date == day
    plan = client.get(f"/api/plans/{day.isoformat()}").json()
    assert len(plan["items"]) == len(raw["action"]["proposed_replan"]["after"])
    session.expire_all()
    revisions = session.scalars(select(PlanRevision).where(PlanRevision.plan_date == day)).all()
    assert len(revisions) == 1
    assert revisions[0].source == "agent"

    # A duplicate confirmation returns the stored result without writing again.
    again = action_service.confirm(action_id, confirm=True)
    assert again.status.value == "confirmed"
    session.expire_all()
    revisions = session.scalars(select(PlanRevision).where(PlanRevision.plan_date == day)).all()
    assert len(revisions) == 1


def test_replan_confirmation_rejects_a_stale_plan(
    client: TestClient,
    session: Session,
    task_service: TaskService,
    action_service: PendingActionService,
    create_task: Callable[..., dict],
) -> None:
    day = date.today() + timedelta(days=2)
    task = create_task(title="写第二章", estimated_minutes=60)
    tools = _tools(task_service, action_service)
    raw = json.loads(tools["prepare_replan"].invoke({"plan_date": day.isoformat()}))
    action_id = raw["action"]["id"]

    # Someone edits the same day after the draft was produced.
    manual = client.put(
        f"/api/plans/{day.isoformat()}",
        json={
            "available_minutes": 300,
            "items": [
                {
                    "task_id": task["id"],
                    "start_at": local_iso(day, 15),
                    "end_at": local_iso(day, 16),
                    "note": None,
                }
            ],
        },
    )
    assert manual.status_code == 200, manual.text

    with pytest.raises(PlanVersionConflictError):
        action_service.confirm(action_id, confirm=True)

    plan = client.get(f"/api/plans/{day.isoformat()}").json()
    assert len(plan["items"]) == 1
    assert plan["items"][0]["start_at"].startswith(f"{day.isoformat()}T07:00:00")
    session.expire_all()
    assert session.scalars(select(PlanRevision).where(PlanRevision.plan_date == day)).all() == []


def test_prepare_create_project_confirms_idempotently(
    client: TestClient,
    task_service: TaskService,
    action_service: PendingActionService,
) -> None:
    tools = _tools(task_service, action_service)
    raw = json.loads(
        tools["prepare_create_project"].invoke(
            {
                "name": "支付网关改造",
                "description": "公司项目：对账与退款链路",
                "status": "active",
                "start_date": "2026-11-01",
                "due_date": "2026-12-15",
            }
        )
    )
    assert raw["ok"] is True
    assert raw["kind"] == "project_draft"
    assert "project_draft" in ACTION_KINDS
    action_id = raw["action"]["id"]
    assert all(project["name"] != "支付网关改造" for project in client.get("/api/projects").json())

    confirmed = action_service.confirm(action_id, confirm=True)
    assert confirmed.status.value == "confirmed"
    projects = client.get("/api/projects").json()
    created = [project for project in projects if project["name"] == "支付网关改造"]
    assert len(created) == 1
    assert created[0]["status"] == "active"

    action_service.confirm(action_id, confirm=True)
    projects = client.get("/api/projects").json()
    assert len([p for p in projects if p["name"] == "支付网关改造"]) == 1


def test_prepare_create_project_rejects_bad_dates(
    task_service: TaskService,
    action_service: PendingActionService,
) -> None:
    tools = _tools(task_service, action_service)
    raw = json.loads(
        tools["prepare_create_project"].invoke(
            {"name": "倒置日期", "start_date": "2026-12-31", "due_date": "2026-01-01"}
        )
    )
    assert raw["ok"] is False
    assert raw["kind"] == "validation_error"

    bad = json.loads(
        tools["prepare_create_project"].invoke({"name": "格式错误", "start_date": "明天"})
    )
    assert bad["ok"] is False
    assert bad["kind"] == "validation_error"
