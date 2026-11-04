"""Activity log tests: truthful records tied to successful writes only."""

from __future__ import annotations

from fastapi.testclient import TestClient


def actions_for(client: TestClient, task_id: str) -> list[str]:
    response = client.get(f"/api/activities?task_id={task_id}")
    assert response.status_code == 200
    return [item["action"] for item in response.json()]


def test_task_lifecycle_activity_events(client: TestClient, create_task) -> None:
    task = create_task(title="记录我", due_at="2026-11-10T18:00:00+08:00")
    client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "改名后的我", "priority": "high", "estimated_minutes": 60},
    )
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "pending"})

    actions = actions_for(client, task["id"])
    assert "task_created" in actions
    assert actions.count("task_updated") >= 2
    assert "task_completed" in actions
    assert "task_reopened" in actions

    records = client.get(f"/api/activities?task_id={task['id']}").json()
    completion = next(item for item in records if item["action"] == "task_completed")
    assert completion["task_title"] == "改名后的我"
    assert "完成任务" in completion["summary"]


def test_failed_write_creates_no_success_activity(client: TestClient, create_task) -> None:
    parent = create_task(title="父任务")
    client.post(f"/api/tasks/{parent['id']}/subtasks", json={"title": "子任务"})
    before = client.get(f"/api/activities?task_id={parent['id']}").json()

    blocked = client.patch(f"/api/tasks/{parent['id']}", json={"status": "completed"})
    assert blocked.status_code == 409

    after = client.get(f"/api/activities?task_id={parent['id']}").json()
    assert [item["action"] for item in after] == [item["action"] for item in before]
    assert "task_completed" not in [item["action"] for item in after]


def test_project_change_activity_and_subtask_sync(client: TestClient, create_task) -> None:
    first = client.post("/api/projects", json={"name": "项目甲"}).json()
    second = client.post("/api/projects", json={"name": "项目乙"}).json()
    parent = create_task(title="跟随项目的任务", project_id=first["id"])
    client.post(f"/api/tasks/{parent['id']}/subtasks", json={"title": "子任务"})

    client.patch(f"/api/tasks/{parent['id']}", json={"project_id": second["id"]})
    records = client.get(f"/api/activities?task_id={parent['id']}").json()
    moved = next(item for item in records if item["action"] == "task_project_changed")
    assert moved["old_value"] == "项目甲"
    assert moved["new_value"] == "项目乙"

    project_activities = client.get(f"/api/activities?project_id={second['id']}").json()
    assert any(item["action"] == "task_project_changed" for item in project_activities)


def test_delete_recorded_with_snapshot(client: TestClient, create_task) -> None:
    task = create_task(title="会被删除")
    client.delete(f"/api/tasks/{task['id']}")
    records = client.get(f"/api/activities?task_id={task['id']}").json()
    assert any(item["action"] == "task_deleted" for item in records)
    deleted = next(item for item in records if item["action"] == "task_deleted")
    assert deleted["task_title"] == "会被删除"


def test_project_detail_shows_recent_activity(client: TestClient, create_task) -> None:
    project = client.post("/api/projects", json={"name": "活动项目"}).json()
    create_task(title="项目任务", project_id=project["id"])

    detail = client.get(f"/api/projects/{project['id']}").json()
    summaries = [item["summary"] for item in detail["recent_activities"]]
    assert any("创建任务" in summary for summary in summaries)
    assert any("创建项目" in summary for summary in summaries)
