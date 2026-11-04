"""Project CRUD, progress, archive/restore, and project activity tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def create_project(client: TestClient, **overrides: object) -> dict:
    payload = {
        "name": overrides.pop("name", "AI Agent 项目"),
        "description": overrides.pop("description", "完成一个 AI Agent"),
        "status": overrides.pop("status", "active"),
        "start_date": overrides.pop("start_date", "2026-11-01"),
        "due_date": overrides.pop("due_date", "2026-11-30"),
    }
    payload.update(overrides)
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_projects(client: TestClient) -> None:
    project = create_project(client)
    assert project["name"] == "AI Agent 项目"
    assert project["stats"]["total_tasks"] == 0
    assert project["stats"]["completion_rate"] == 0.0

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [project["id"]]


def test_project_validation_errors(client: TestClient) -> None:
    empty = client.post("/api/projects", json={"name": "   "})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "VALIDATION_ERROR"

    reversed_dates = client.post(
        "/api/projects",
        json={"name": "倒序项目", "start_date": "2026-11-10", "due_date": "2026-11-01"},
    )
    assert reversed_dates.status_code == 422

    missing = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_project_update_and_date_validation(client: TestClient) -> None:
    project = create_project(client)
    updated = client.patch(f"/api/projects/{project['id']}", json={"name": "改名后的项目"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名后的项目"

    invalid = client.patch(f"/api/projects/{project['id']}", json={"start_date": "2026-12-01"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_DATE_RANGE"

    empty_patch = client.patch(f"/api/projects/{project['id']}", json={})
    assert empty_patch.status_code == 422


def test_project_progress_uses_real_task_data(client: TestClient, create_task) -> None:
    project = create_project(client)
    first = create_task(title="任务一", project_id=project["id"])
    create_task(title="任务二", project_id=project["id"])
    create_task(title="项目外任务")

    client.patch(f"/api/tasks/{first['id']}", json={"status": "completed"})
    detail = client.get(f"/api/projects/{project['id']}").json()
    stats = detail["project"]["stats"]
    assert stats["total_tasks"] == 2
    assert stats["completed_tasks"] == 1
    assert stats["pending_tasks"] == 1
    assert stats["completion_rate"] == 50.0
    assert len(detail["tasks"]) == 2
    assert detail["recent_activities"]

    empty_project = create_project(client, name="空项目")
    assert empty_project["stats"]["completion_rate"] == 0.0


def test_project_overdue_tasks_counted(client: TestClient, create_task) -> None:
    project = create_project(client)
    create_task(
        title="已经逾期",
        project_id=project["id"],
        due_at="2020-01-01T09:00:00+08:00",
    )
    detail = client.get(f"/api/projects/{project['id']}").json()
    assert detail["project"]["stats"]["overdue_tasks"] == 1


def test_archive_and_restore_preserve_tasks(client: TestClient, create_task) -> None:
    project = create_project(client)
    task = create_task(title="归档前任务", project_id=project["id"])

    archived = client.post(f"/api/projects/{project['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["stats"]["total_tasks"] == 1

    default_list = client.get("/api/projects?include_archived=false")
    assert all(item["id"] != project["id"] for item in default_list.json())

    blocked = client.post(
        "/api/tasks", json={"title": "归档项目新任务", "project_id": project["id"]}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROJECT_ARCHIVED"

    task_after = client.get(f"/api/tasks/{task['id']}")
    assert task_after.status_code == 200

    restored = client.post(f"/api/projects/{project['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    assert restored.json()["stats"]["total_tasks"] == 1


def test_project_activities_are_recorded(client: TestClient) -> None:
    project = create_project(client)
    client.patch(f"/api/projects/{project['id']}", json={"description": "更新描述"})
    client.post(f"/api/projects/{project['id']}/archive")

    activities = client.get(f"/api/activities?project_id={project['id']}").json()
    actions = [item["action"] for item in activities]
    assert "project_created" in actions
    assert "project_updated" in actions
    assert "project_status_changed" in actions
    assert activities[0]["project_name"] == "AI Agent 项目"


def test_assign_task_to_project_and_move_it(client: TestClient, create_task) -> None:
    first = create_project(client, name="项目一")
    second = create_project(client, name="项目二")
    task = create_task(title="可移动任务", project_id=first["id"])
    assert task["project_id"] == first["id"]

    moved = client.patch(f"/api/tasks/{task['id']}", json={"project_id": second["id"]})
    assert moved.status_code == 200
    assert moved.json()["project_id"] == second["id"]

    cleared = client.patch(f"/api/tasks/{task['id']}", json={"project_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["project_id"] is None

    filtered = client.get(f"/api/tasks?project_id={second['id']}").json()
    assert filtered == []
