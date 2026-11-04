"""Daily plan validation, persistence, capacity, and deterministic suggestions."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

TIMEZONE = ZoneInfo("Asia/Shanghai")


def today_local():
    return datetime.now(TIMEZONE).date()


def at_local(plan_date, hour: int, minute: int = 0) -> str:
    return datetime.combine(plan_date, time(hour, minute), tzinfo=TIMEZONE).isoformat()


def make_task(client: TestClient, title: str, **overrides: object) -> dict:
    payload: dict[str, object] = {"title": title}
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def plan_body(items: list[dict], available_minutes: int = 300) -> dict:
    return {"available_minutes": available_minutes, "items": items}


def test_save_get_and_delete_plan(client: TestClient) -> None:
    plan_date = today_local()
    first = make_task(client, "任务一", estimated_minutes=60)
    second = make_task(client, "任务二", estimated_minutes=90)

    response = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": first["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                },
                {
                    "task_id": second["id"],
                    "start_at": at_local(plan_date, 10, 30),
                    "end_at": at_local(plan_date, 12),
                    "note": "留出半小时休息",
                },
            ]
        ),
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["plan_date"] == plan_date.isoformat()
    assert plan["planned_minutes"] == 150
    assert [item["task_title"] for item in plan["items"]] == ["任务一", "任务二"]
    assert plan["items"][1]["note"] == "留出半小时休息"

    fetched = client.get(f"/api/plans/{plan_date.isoformat()}")
    assert fetched.status_code == 200
    assert fetched.json()["planned_minutes"] == 150

    deleted = client.delete(f"/api/plans/{plan_date.isoformat()}")
    assert deleted.status_code == 204
    assert client.get(f"/api/plans/{plan_date.isoformat()}").status_code == 404


def test_plan_replaces_existing_schedule(client: TestClient) -> None:
    plan_date = today_local()
    first = make_task(client, "任务一", estimated_minutes=30)
    second = make_task(client, "任务二", estimated_minutes=30)
    client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": first["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                }
            ]
        ),
    )
    replaced = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": second["id"],
                    "start_at": at_local(plan_date, 14),
                    "end_at": at_local(plan_date, 15),
                }
            ]
        ),
    )
    assert replaced.status_code == 200
    assert [item["task_title"] for item in replaced.json()["items"]] == ["任务二"]


def test_plan_rejects_overlap_and_excess_capacity(client: TestClient) -> None:
    plan_date = today_local()
    first = make_task(client, "任务一", estimated_minutes=60)
    second = make_task(client, "任务二", estimated_minutes=60)

    overlap = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": first["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10, 30),
                },
                {
                    "task_id": second["id"],
                    "start_at": at_local(plan_date, 10),
                    "end_at": at_local(plan_date, 11),
                },
            ]
        ),
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "PLAN_CONFLICT"

    excess = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": first["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                }
            ],
            available_minutes=30,
        ),
    )
    assert excess.status_code == 409
    assert excess.json()["error"]["details"]["planned_minutes"] == 60


def test_plan_rejects_completed_and_unknown_tasks(client: TestClient) -> None:
    plan_date = today_local()
    done = make_task(client, "已完成任务")
    client.patch(f"/api/tasks/{done['id']}", json={"status": "completed"})

    completed = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": done["id"],
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                }
            ]
        ),
    )
    assert completed.status_code == 409

    unknown = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": "00000000-0000-0000-0000-000000000000",
                    "start_at": at_local(plan_date, 9),
                    "end_at": at_local(plan_date, 10),
                }
            ]
        ),
    )
    assert unknown.status_code == 404


def test_plan_blocks_must_be_on_the_plan_local_date(client: TestClient) -> None:
    plan_date = today_local()
    task = make_task(client, "任务")
    previous_day = plan_date - timedelta(days=1)
    response = client.put(
        f"/api/plans/{plan_date.isoformat()}",
        json=plan_body(
            [
                {
                    "task_id": task["id"],
                    "start_at": at_local(previous_day, 23),
                    "end_at": at_local(plan_date, 0, 30),
                }
            ]
        ),
    )
    assert response.status_code == 409


def test_plan_suggestion_is_bounded_and_truthful(client: TestClient, session) -> None:
    from app.services.planning_service import PlanningService

    plan_date = today_local()
    make_task(client, "高优先级任务", priority="high", estimated_minutes=60)
    make_task(client, "低优先级任务", priority="low", estimated_minutes=60)
    container = make_task(client, "容器任务", estimated_minutes=120)
    client.post(f"/api/tasks/{container['id']}/subtasks", json={"title": "子任务"})
    done = make_task(client, "已完成任务", estimated_minutes=60)
    client.patch(f"/api/tasks/{done['id']}", json={"status": "completed"})

    # A fixed morning "now" keeps the assertion independent of the wall clock.
    fixed_now = datetime.combine(plan_date, time(9, 0), tzinfo=TIMEZONE)
    service = PlanningService(session, timezone=TIMEZONE)
    blocks = service.suggest_blocks(plan_date, 120, now=fixed_now)
    assert blocks
    assert sum(int(block["estimated_minutes"]) for block in blocks) <= 120
    titles = [str(block["title"]) for block in blocks]
    assert "已完成任务" not in titles
    assert "容器任务" not in titles
    assert titles[0] == "高优先级任务"

    starts = [block["start_at"] for block in blocks]
    ends = [block["end_at"] for block in blocks]
    for index in range(len(starts) - 1):
        assert ends[index] <= starts[index + 1]

    smoke = client.get(f"/api/plans/{plan_date.isoformat()}/suggestion?available_minutes=120")
    assert smoke.status_code == 200
    assert smoke.json()["available_minutes"] == 120
