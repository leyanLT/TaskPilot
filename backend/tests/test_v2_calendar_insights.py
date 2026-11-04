"""V2.0 F04/F06: calendar time blocks and rule-based risk insights."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

TZ = ZoneInfo("Asia/Shanghai")


def today() -> date:
    return datetime.now(TZ).date()


def local_iso(day: date, hour: int, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ).isoformat()


def test_time_block_crud_stays_in_sync_with_daily_plan(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    task = create_task(title="写章节初稿")
    day = today()

    created = client.post(
        "/api/time-blocks",
        json={
            "plan_date": day.isoformat(),
            "task_id": task["id"],
            "start_at": local_iso(day, 9),
            "end_at": local_iso(day, 10),
        },
    )
    assert created.status_code == 201, created.text
    block = created.json()
    assert block["task_title"] == "写章节初稿"

    # The daily plan endpoint reads the very same row.
    plan = client.get(f"/api/plans/{day.isoformat()}").json()
    assert [item["task_id"] for item in plan["items"]] == [task["id"]]

    calendar = client.get(
        "/api/calendar", params={"start": day.isoformat(), "end": day.isoformat()}
    ).json()
    assert calendar["days"][0]["blocks"][0]["id"] == block["id"]
    assert calendar["total_planned_minutes"] == 60

    moved = client.patch(
        f"/api/time-blocks/{block['id']}",
        json={"start_at": local_iso(day, 14), "end_at": local_iso(day, 15, 30)},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["start_at"].startswith(f"{day.isoformat()}T06:00:00")

    plan_after = client.get(f"/api/plans/{day.isoformat()}").json()
    assert datetime.fromisoformat(plan_after["items"][0]["start_at"]) == datetime.fromisoformat(
        moved.json()["start_at"]
    )

    removed = client.delete(f"/api/time-blocks/{block['id']}")
    assert removed.status_code == 204
    assert client.get(f"/api/plans/{day.isoformat()}").json()["items"] == []


def test_time_block_rejects_conflicts_and_bad_ranges(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    day = today()
    first = create_task(title="任务甲")
    second = create_task(title="任务乙")
    assert (
        client.post(
            "/api/time-blocks",
            json={
                "plan_date": day.isoformat(),
                "task_id": first["id"],
                "start_at": local_iso(day, 9),
                "end_at": local_iso(day, 10),
            },
        ).status_code
        == 201
    )

    overlap = client.post(
        "/api/time-blocks",
        json={
            "plan_date": day.isoformat(),
            "task_id": second["id"],
            "start_at": local_iso(day, 9, 30),
            "end_at": local_iso(day, 10, 30),
        },
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "PLAN_CONFLICT"

    bad_range = client.post(
        "/api/time-blocks",
        json={
            "plan_date": day.isoformat(),
            "task_id": second["id"],
            "start_at": local_iso(day, 12),
            "end_at": local_iso(day, 11),
        },
    )
    assert bad_range.status_code == 422

    cross_day = client.post(
        "/api/time-blocks",
        json={
            "plan_date": day.isoformat(),
            "task_id": second["id"],
            "start_at": local_iso(day, 23),
            "end_at": local_iso(day + timedelta(days=1), 1),
        },
    )
    assert cross_day.status_code == 409


def test_calendar_filters_by_project(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    project_a = client.post("/api/projects", json={"name": "项目甲"}).json()
    project_b = client.post("/api/projects", json={"name": "项目乙"}).json()
    task_a = create_task(title="甲任务", project_id=project_a["id"])
    task_b = create_task(title="乙任务", project_id=project_b["id"])
    day = today()
    for task in (task_a, task_b):
        assert (
            client.post(
                "/api/time-blocks",
                json={
                    "plan_date": day.isoformat(),
                    "task_id": task["id"],
                    "start_at": local_iso(day, 9 if task is task_a else 11),
                    "end_at": local_iso(day, 10 if task is task_a else 12),
                },
            ).status_code
            == 201
        )

    filtered = client.get(
        "/api/calendar",
        params={
            "start": day.isoformat(),
            "end": day.isoformat(),
            "project_id": project_b["id"],
        },
    ).json()
    titles = [block["task_title"] for block in filtered["days"][0]["blocks"]]
    assert titles == ["乙任务"]


def test_insights_cover_overdue_blocked_project_and_dismissal(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    yesterday = datetime.now(TZ) - timedelta(days=1)
    create_task(title="逾期任务", due_at=yesterday.isoformat())

    prerequisite = create_task(title="前置任务")
    dependent = create_task(title="被挡住的后续")
    client.post(
        f"/api/dependencies/{dependent['id']}",
        json={"depends_on_task_id": prerequisite["id"]},
    )

    project = client.post(
        "/api/projects",
        json={
            "name": "即将截止的项目",
            "status": "active",
            "start_date": (today() - timedelta(days=10)).isoformat(),
            "due_date": (today() + timedelta(days=5)).isoformat(),
        },
    ).json()
    create_task(title="项目里的任务", project_id=project["id"])

    insights = client.get("/api/insights").json()
    keys = {item["key"] for item in insights["items"]}
    assert "overdue" in keys
    assert "blocked" in keys
    assert f"project:{project['id']}" in keys
    overdue = next(item for item in insights["items"] if item["key"] == "overdue")
    assert overdue["severity"] == "high"
    assert overdue["task_titles"] == ["逾期任务"]

    dismissed = client.post("/api/insights/dismiss", json={"key": "overdue"})
    assert dismissed.status_code == 204
    after = client.get("/api/insights").json()
    assert "overdue" not in {item["key"] for item in after["items"]}
    assert after["dismissed_count"] >= 1


def test_insights_report_workload_over_capacity(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    client.patch("/api/preferences", json={"daily_available_minutes": 60})
    for index in range(4):
        create_task(title=f"重活{index}", estimated_minutes=120)

    insights = client.get("/api/insights").json()
    workload = next((item for item in insights["items"] if item["key"] == "workload"), None)
    assert workload is not None
    assert workload["metric"]["demand_minutes"] >= 480
    assert workload["metric"]["capacity_minutes"] >= 60
