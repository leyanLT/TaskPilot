"""Notification generation, dedupe, read state, and completion cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService
from fastapi.testclient import TestClient

TIMEZONE = ZoneInfo("Asia/Shanghai")


def test_reminders_are_derived_from_real_tasks_and_deduped(
    client: TestClient, create_task, session
) -> None:
    now = datetime(2026, 11, 3, 10, 0, tzinfo=TIMEZONE)
    overdue = create_task(
        title="逾期任务",
        due_at=(now - timedelta(hours=2)).isoformat(),
    )
    due_soon = create_task(
        title="即将截止任务",
        due_at=(now + timedelta(hours=3)).isoformat(),
    )
    today = create_task(
        title="今日任务",
        due_at=datetime(2026, 11, 3, 20, 0, tzinfo=TIMEZONE).isoformat(),
    )
    completed = create_task(
        title="已完成任务",
        due_at=(now + timedelta(hours=2)).isoformat(),
    )
    client.patch(f"/api/tasks/{completed['id']}", json={"status": "completed"})

    service = NotificationService(session, timezone=TIMEZONE)
    service.sync(now=now)

    repository = NotificationRepository(session)
    rows = repository.list(limit=100)
    assert rows
    by_task: dict[str, set[str]] = {}
    for row in rows:
        by_task.setdefault(str(row.task_id), set()).add(row.type)
    assert "overdue" in by_task[overdue["id"]]
    assert "due_soon" in by_task[due_soon["id"]]
    assert "today_todo" in by_task[today["id"]]
    assert completed["id"] not in by_task
    assert repository.unread_count() == len(rows)

    count_before = len(rows)
    service.sync(now=now)
    assert len(repository.list(limit=100)) == count_before


def test_read_state_persists_and_completed_task_reminders_disappear(
    client: TestClient, create_task, session
) -> None:
    now = datetime(2026, 11, 3, 10, 0, tzinfo=TIMEZONE)
    task = create_task(
        title="读我",
        due_at=(now - timedelta(hours=1)).isoformat(),
    )
    service = NotificationService(session, timezone=TIMEZONE)
    service.sync(now=now)
    repository = NotificationRepository(session)
    rows = repository.list(limit=100)
    for row in rows:
        service.mark_read(row.id)
    assert repository.unread_count() == 0

    service.sync(now=now)
    still_there = repository.list(limit=10)
    assert still_there
    assert all(row.read_at is not None for row in still_there)

    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    service.sync(now=now)
    assert repository.list(limit=10) == []


def test_notification_api_returns_persisted_state(client: TestClient, create_task) -> None:
    create_task(
        title="接口提醒一",
        due_at="2020-01-01T09:00:00+08:00",
    )
    create_task(
        title="接口提醒二",
        due_at="2020-01-02T09:00:00+08:00",
    )
    listed = client.get("/api/notifications")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["unread_count"] >= 2
    assert any(item["type"] == "overdue" for item in payload["items"])

    refreshed = client.post("/api/notifications/refresh")
    assert refreshed.status_code == 200
    same = refreshed.json()
    assert len(same["items"]) == len(payload["items"])

    first_id = same["items"][0]["id"]
    if same["items"][0]["read_at"] is None:
        marked = client.patch(f"/api/notifications/{first_id}", json={"read": True})
        assert marked.status_code == 200
        assert marked.json()["read_at"] is not None

    unread_only = client.get("/api/notifications?unread_only=true").json()
    assert all(item["read_at"] is None for item in unread_only["items"])
    assert unread_only["unread_count"] >= 1

    read_all = client.post("/api/notifications/read-all")
    assert read_all.status_code == 200
    assert read_all.json()["count"] >= 1
    assert client.get("/api/notifications/unread-count").json()["count"] == 0


def test_notification_not_found(client: TestClient) -> None:
    response = client.patch(
        "/api/notifications/00000000-0000-0000-0000-000000000000",
        json={"read": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"
