"""Subtask hierarchy, completion guard, cascade delete, ordering, and progress."""

from __future__ import annotations

from fastapi.testclient import TestClient


def make_project(client: TestClient) -> dict:
    response = client.post(
        "/api/projects",
        json={"name": "父子任务项目", "status": "active"},
    )
    assert response.status_code == 201
    return response.json()


def add_subtask(client: TestClient, parent_id: str, title: str, **overrides: object) -> dict:
    payload: dict[str, object] = {"title": title}
    payload.update(overrides)
    response = client.post(f"/api/tasks/{parent_id}/subtasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_subtask_inherits_project_and_counts(client: TestClient, create_task) -> None:
    project = make_project(client)
    parent = create_task(title="搭建 Agent", project_id=project["id"])
    child = add_subtask(
        client,
        parent["id"],
        "设计工具 schema",
        priority="high",
        estimated_minutes=45,
    )
    assert child["parent_id"] == parent["id"]
    assert child["project_id"] == project["id"]
    assert child["priority"] == "high"
    assert child["estimated_minutes"] == 45

    detail = client.get(f"/api/tasks/{parent['id']}").json()
    assert detail["subtask_count"] == 1
    assert detail["completed_subtask_count"] == 0
    assert [item["title"] for item in detail["subtasks"]] == ["设计工具 schema"]

    listed = client.get("/api/tasks").json()
    assert [item["title"] for item in listed] == ["搭建 Agent"]

    flat = client.get("/api/tasks?include_subtasks=true").json()
    assert {item["title"] for item in flat} == {"搭建 Agent", "设计工具 schema"}


def test_two_level_hierarchy_is_enforced(client: TestClient, create_task) -> None:
    parent = create_task(title="父任务")
    child = add_subtask(client, parent["id"], "子任务")

    nested = client.post(f"/api/tasks/{child['id']}/subtasks", json={"title": "孙任务"})
    assert nested.status_code == 409
    assert nested.json()["error"]["code"] == "TASK_HIERARCHY_INVALID"


def test_parent_cannot_complete_with_unfinished_subtasks(client: TestClient, create_task) -> None:
    parent = create_task(title="父任务")
    child = add_subtask(client, parent["id"], "子任务")

    blocked = client.patch(f"/api/tasks/{parent['id']}", json={"status": "completed"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_HAS_UNFINISHED_SUBTASKS"
    assert blocked.json()["error"]["details"]["unfinished_subtasks"] == 1

    assert client.get(f"/api/tasks/{parent['id']}").json()["status"] == "pending"

    client.patch(f"/api/tasks/{child['id']}", json={"status": "completed"})
    completed = client.patch(f"/api/tasks/{parent['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None
    assert completed.json()["completed_subtask_count"] == 1


def test_reopen_clears_completed_at(client: TestClient, create_task) -> None:
    task = create_task(title="可重开任务")
    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).json()
    assert done["completed_at"] is not None

    reopened = client.patch(f"/api/tasks/{task['id']}", json={"status": "pending"}).json()
    assert reopened["status"] == "pending"
    assert reopened["completed_at"] is None


def test_delete_parent_requires_explicit_confirmation(client: TestClient, create_task) -> None:
    parent = create_task(title="要删除的父任务")
    child = add_subtask(client, parent["id"], "要一起删除的子任务")

    blocked = client.delete(f"/api/tasks/{parent['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_HAS_SUBTASKS"
    assert blocked.json()["error"]["details"]["subtask_count"] == 1

    confirmed = client.delete(f"/api/tasks/{parent['id']}?confirm_subtasks=true")
    assert confirmed.status_code == 204
    assert client.get(f"/api/tasks/{parent['id']}").status_code == 404
    assert client.get(f"/api/tasks/{child['id']}").status_code == 404


def test_subtask_project_follows_parent(client: TestClient, create_task) -> None:
    first = make_project(client)
    second = client.post("/api/projects", json={"name": "第二个项目"}).json()
    parent = create_task(title="父任务", project_id=first["id"])
    child = add_subtask(client, parent["id"], "子任务")

    updated = client.patch(f"/api/tasks/{parent['id']}", json={"project_id": second["id"]})
    assert updated.status_code == 200
    child_after = client.get(f"/api/tasks/{child['id']}").json()
    assert child_after["project_id"] == second["id"]

    rejected = client.patch(f"/api/tasks/{child['id']}", json={"project_id": first["id"]})
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "TASK_HIERARCHY_INVALID"


def test_reorder_subtasks(client: TestClient, create_task) -> None:
    parent = create_task(title="排序父任务")
    first = add_subtask(client, parent["id"], "步骤一")
    second = add_subtask(client, parent["id"], "步骤二")
    third = add_subtask(client, parent["id"], "步骤三")

    reordered = client.put(
        f"/api/tasks/{parent['id']}/subtasks/order",
        json={"subtask_ids": [third["id"], first["id"], second["id"]]},
    )
    assert reordered.status_code == 200
    assert [item["title"] for item in reordered.json()] == ["步骤三", "步骤一", "步骤二"]

    invalid = client.put(
        f"/api/tasks/{parent['id']}/subtasks/order",
        json={"subtask_ids": [first["id"]]},
    )
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "INVALID_SUBTASK_ORDER"


def test_project_stats_use_leaf_tasks(client: TestClient, create_task) -> None:
    project = make_project(client)
    parent = create_task(title="父任务", project_id=project["id"])
    first = add_subtask(client, parent["id"], "子任务一")
    add_subtask(client, parent["id"], "子任务二")

    client.patch(f"/api/tasks/{first['id']}", json={"status": "completed"})
    stats = client.get(f"/api/projects/{project['id']}").json()["project"]["stats"]
    assert stats["total_tasks"] == 2
    assert stats["completed_tasks"] == 1
    assert stats["completion_rate"] == 50.0
