"""V2.0 F02/F03: recurring rules and focus sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.models import FocusSession, RecurrenceRule, Task
from app.services.recurrence_service import RecurrenceService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

TZ = ZoneInfo("Asia/Shanghai")


def today() -> date:
    return datetime.now(TZ).date()


def _rule(**overrides: object) -> RecurrenceRule:
    payload: dict[str, object] = {
        "title": "每天阅读论文",
        "frequency": "daily",
        "interval": 1,
        "start_date": date(2026, 1, 1),
        "timezone": "Asia/Shanghai",
        "priority": "medium",
        "paused": False,
    }
    payload.update(overrides)
    return RecurrenceRule(**payload)


# -- pure occurrence math -----------------------------------------------------


@pytest.mark.parametrize(
    ("frequency", "weekdays", "start", "until", "expected"),
    [
        ("daily", None, date(2026, 1, 1), date(2026, 1, 3), [date(2026, 1, d) for d in (1, 2, 3)]),
        (
            "weekly",
            None,
            date(2026, 1, 5),
            date(2026, 1, 19),
            [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)],
        ),
        (
            "monthly",
            None,
            date(2026, 1, 31),
            date(2026, 4, 30),
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        ),
        (
            "custom_weekly",
            [0, 2, 4],
            date(2026, 1, 5),
            date(2026, 1, 18),
            [
                date(2026, 1, 5),
                date(2026, 1, 7),
                date(2026, 1, 9),
                date(2026, 1, 12),
                date(2026, 1, 14),
                date(2026, 1, 16),
            ],
        ),
    ],
)
def test_occurrence_dates(
    session: Session,
    frequency: str,
    weekdays: list[int] | None,
    start: date,
    until: date,
    expected: list[date],
) -> None:
    service = RecurrenceService(session, timezone=TZ)
    rule = _rule(frequency=frequency, weekdays=weekdays, start_date=start)
    assert list(service.occurrence_dates(rule, until)) == expected


def test_end_date_and_interval_bound_the_series(session: Session) -> None:
    service = RecurrenceService(session, timezone=TZ)
    rule = _rule(
        frequency="daily",
        interval=2,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
    )
    assert list(service.occurrence_dates(rule, date(2026, 2, 1))) == [
        date(2026, 1, 1),
        date(2026, 1, 3),
        date(2026, 1, 5),
        date(2026, 1, 7),
    ]


# -- API lifecycle ------------------------------------------------------------


def test_daily_rule_generation_is_idempotent(client: TestClient) -> None:
    response = client.post(
        "/api/recurrences",
        json={
            "title": "每天阅读论文",
            "frequency": "daily",
            "start_date": today().isoformat(),
            "due_time": "09:00",
        },
    )
    assert response.status_code == 201, response.text
    rule = response.json()
    assert rule["generated_count"] == 15  # today .. today + 14
    assert rule["next_occurrence"] == today().isoformat()

    again = client.post("/api/recurrences/generate")
    assert again.status_code == 200
    assert again.json()["created"] == 0

    tasks = client.get("/api/tasks").json()
    matching = [task for task in tasks if task["title"] == "每天阅读论文"]
    assert len(matching) == 15
    assert any(
        (task["due_at"] or "").startswith(f"{today().isoformat()}T01:00:00") for task in matching
    )


def test_pause_resume_and_delete_scopes(
    client: TestClient,
    session: Session,
) -> None:
    created = client.post(
        "/api/recurrences",
        json={
            "title": "每周整理周报",
            "frequency": "weekly",
            "start_date": (today() - timedelta(days=7)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    rule_id = rule["id"]

    paused = client.post(f"/api/recurrences/{rule_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert client.post("/api/recurrences/generate").json()["created"] == 0

    resumed = client.post(f"/api/recurrences/{rule_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False

    instances = list(session.scalars(select(Task).where(Task.recurrence_rule_id == rule_id)))
    assert len(instances) >= 2

    # Completing one occurrence never ends the series.
    client.patch(f"/api/tasks/{instances[0].id}", json={"status": "completed"})
    assert client.get(f"/api/recurrences/{rule_id}").json()["paused"] is False

    # Renaming the rule replaces future pending instances but keeps history.
    updated = client.patch(f"/api/recurrences/{rule_id}", json={"title": "每周整理科研周报"})
    assert updated.status_code == 200, updated.text
    session.expire_all()
    rows = list(session.scalars(select(Task).where(Task.recurrence_rule_id == rule_id)))
    future = [row for row in rows if row.occurrence_date and row.occurrence_date >= today()]
    assert all(row.title == "每周整理科研周报" for row in future)
    assert any(row.status == "completed" for row in rows)

    removed = client.delete(f"/api/recurrences/{rule_id}")
    assert removed.status_code == 204
    session.expire_all()
    remaining = list(session.scalars(select(Task).where(Task.recurrence_rule_id == rule_id)))
    assert remaining == []
    survived = session.get(Task, instances[0].id)
    assert survived is not None
    assert survived.recurrence_rule_id is None


def test_monthly_and_custom_rules_validate_input(client: TestClient) -> None:
    bad_weekdays = client.post(
        "/api/recurrences",
        json={
            "title": "自定义",
            "frequency": "custom_weekly",
            "start_date": today().isoformat(),
        },
    )
    assert bad_weekdays.status_code == 422

    weekday_on_daily = client.post(
        "/api/recurrences",
        json={
            "title": "冲突",
            "frequency": "daily",
            "weekdays": [0, 2],
            "start_date": today().isoformat(),
        },
    )
    assert weekday_on_daily.status_code == 422

    bad_range = client.post(
        "/api/recurrences",
        json={
            "title": "日期倒置",
            "frequency": "daily",
            "start_date": today().isoformat(),
            "end_date": (today() - timedelta(days=1)).isoformat(),
        },
    )
    assert bad_range.status_code == 422


# -- focus --------------------------------------------------------------------


def _start_focus(client: TestClient, task_id: str) -> dict:
    response = client.post("/api/focus/start", json={"task_id": task_id, "planned_minutes": 25})
    assert response.status_code == 200, response.text
    return response.json()


def test_focus_lifecycle_uses_server_clock(
    client: TestClient,
    session: Session,
    create_task: Callable[..., dict],
) -> None:
    task = create_task(title="写周报")
    started = _start_focus(client, task["id"])
    assert started["status"] == "running"

    row = session.get(FocusSession, started["id"])
    assert row is not None
    row.last_resumed_at = datetime.now(UTC) - timedelta(seconds=90)
    session.commit()

    active = client.get("/api/focus/active").json()
    assert active["id"] == started["id"]
    assert active["elapsed_seconds"] >= 90
    assert active["remaining_seconds"] <= 25 * 60 - 90

    paused = client.post(f"/api/focus/{started['id']}/pause").json()
    assert paused["status"] == "paused"
    frozen = paused["elapsed_seconds"]
    again = client.get("/api/focus/active").json()
    assert again["elapsed_seconds"] == frozen

    resumed = client.post(f"/api/focus/{started['id']}/resume").json()
    assert resumed["status"] == "running"

    stopped = client.post(f"/api/focus/{started['id']}/stop").json()
    assert stopped["status"] == "completed"
    assert stopped["elapsed_seconds"] >= frozen
    idempotent = client.post(f"/api/focus/{started['id']}/stop").json()
    assert idempotent["accumulated_seconds"] == stopped["accumulated_seconds"]
    assert client.get("/api/focus/active").json() is None

    stats = client.get("/api/focus/stats").json()
    assert stats["today_seconds"] >= frozen
    assert len(stats["by_day"]) == 7
    assert stats["by_task"][0]["title"] == "写周报"


def test_only_one_active_focus_session(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    first = create_task(title="任务一")
    second = create_task(title="任务二")
    _start_focus(client, first["id"])

    conflict = client.post("/api/focus/start", json={"task_id": second["id"]})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "FOCUS_CONFLICT"

    # Starting again for the same task is idempotent, not a second session.
    same = client.post("/api/focus/start", json={"task_id": first["id"]})
    assert same.status_code == 200

    completed = create_task(title="已完成任务")
    client.patch(f"/api/tasks/{completed['id']}", json={"status": "completed"})
    active = client.get("/api/focus/active").json()
    client.post(f"/api/focus/{active['id']}/stop")
    rejected = client.post("/api/focus/start", json={"task_id": completed["id"]})
    assert rejected.status_code == 409


def test_focus_stats_cover_real_records(
    client: TestClient,
    session: Session,
    create_task: Callable[..., dict],
) -> None:
    task = create_task(title="统计任务")
    started = _start_focus(client, task["id"])
    row = session.get(FocusSession, started["id"])
    row.accumulated_seconds = 1800
    row.last_resumed_at = None
    row.status = "completed"
    row.ended_at = datetime.now(UTC)
    session.commit()

    stats = client.get("/api/focus/stats").json()
    assert stats["today_seconds"] >= 1800
    assert stats["week_seconds"] >= 1800
    assert any(day["seconds"] >= 1800 for day in stats["by_day"])
