"""V2.0 F01: dependency rules, blocking and completion guards."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def _project(client: TestClient, name: str = "依赖项目") -> dict:
    response = client.post("/api/projects", json={"name": name, "status": "active"})
    assert response.status_code == 201, response.text
    return response.json()


def test_dependency_blocks_completion_until_prerequisite_done(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    prerequisite = create_task(title="数据库设计")
    dependent = create_task(title="后端接口")

    created = client.post(
        f"/api/dependencies/{dependent['id']}",
        json={"depends_on_task_id": prerequisite["id"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["depends_on_title"] == "数据库设计"

    view = client.get(f"/api/dependencies/{dependent['id']}").json()
    assert view["is_blocked"] is True
    assert [item["depends_on_title"] for item in view["depends_on"]] == ["数据库设计"]

    # blocked completion returns the documented 409
    blocked = client.patch(f"/api/tasks/{dependent['id']}", json={"status": "completed"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_BLOCKED"

    assert (
        client.patch(f"/api/tasks/{prerequisite['id']}", json={"status": "completed"}).status_code
        == 200
    )

    unblocked = client.get(f"/api/dependencies/{dependent['id']}").json()
    assert unblocked["is_blocked"] is False

    finished = client.patch(f"/api/tasks/{dependent['id']}", json={"status": "completed"})
    assert finished.status_code == 200
    assert finished.json()["status"] == "completed"


def test_reopening_prerequisite_blocks_dependent_again(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    first = create_task(title="前置")
    second = create_task(title="后续")
    client.post(
        f"/api/dependencies/{second['id']}",
        json={"depends_on_task_id": first["id"]},
    )
    client.patch(f"/api/tasks/{first['id']}", json={"status": "completed"})
    assert (
        client.patch(f"/api/tasks/{second['id']}", json={"status": "completed"}).status_code == 200
    )
    client.patch(f"/api/tasks/{first['id']}", json={"status": "pending"})

    summary = client.get("/api/dependencies/summary").json()
    assert second["id"] not in summary  # already completed, not a pending task
    client.patch(f"/api/tasks/{second['id']}", json={"status": "pending"})
    summary = client.get("/api/dependencies/summary").json()
    assert summary[second["id"]] == ["前置"]


def test_rejects_self_duplicate_and_cycle(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    first = create_task(title="A")
    second = create_task(title="B")
    third = create_task(title="C")

    self_link = client.post(
        f"/api/dependencies/{first['id']}",
        json={"depends_on_task_id": first["id"]},
    )
    assert self_link.status_code == 422
    assert self_link.json()["error"]["code"] == "DEPENDENCY_SELF"

    assert (
        client.post(
            f"/api/dependencies/{second['id']}",
            json={"depends_on_task_id": first["id"]},
        ).status_code
        == 201
    )
    duplicate = client.post(
        f"/api/dependencies/{second['id']}",
        json={"depends_on_task_id": first["id"]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DEPENDENCY_DUPLICATE"

    assert (
        client.post(
            f"/api/dependencies/{third['id']}",
            json={"depends_on_task_id": second["id"]},
        ).status_code
        == 201
    )
    cycle = client.post(
        f"/api/dependencies/{first['id']}",
        json={"depends_on_task_id": third["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "DEPENDENCY_CYCLE"


def test_dependency_scope_follows_project(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    project_a = _project(client, "项目甲")
    project_b = _project(client, "项目乙")
    task_a = create_task(title="甲任务", project_id=project_a["id"])
    task_b = create_task(title="乙任务", project_id=project_b["id"])

    mismatch = client.post(
        f"/api/dependencies/{task_a['id']}",
        json={"depends_on_task_id": task_b["id"]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "DEPENDENCY_SCOPE"

    same_project_task = create_task(title="甲任务二", project_id=project_a["id"])
    assert (
        client.post(
            f"/api/dependencies/{task_a['id']}",
            json={"depends_on_task_id": same_project_task["id"]},
        ).status_code
        == 201
    )

    # Moving one side to another project would break the dependency scope.
    moved = client.patch(f"/api/tasks/{task_a['id']}", json={"project_id": project_b["id"]})
    assert moved.status_code == 409
    assert moved.json()["error"]["code"] == "DEPENDENCY_SCOPE"


def test_remove_dependency_and_parent_child_guard(
    client: TestClient,
    create_task: Callable[..., dict],
) -> None:
    parent = create_task(title="父任务")
    child_response = client.post(f"/api/tasks/{parent['id']}/subtasks", json={"title": "子任务"})
    assert child_response.status_code == 201, child_response.text
    child = child_response.json()
    sibling_of_parent = create_task(title="同项目任务")

    hierarchy = client.post(
        f"/api/dependencies/{child['id']}",
        json={"depends_on_task_id": sibling_of_parent["id"]},
    )
    # The child inherits the parent's (empty) project, so the scope is valid; the
    # parent/child guard only rejects dependencies inside the same hierarchy.
    assert hierarchy.status_code == 201

    parent_child = client.post(
        f"/api/dependencies/{parent['id']}",
        json={"depends_on_task_id": child["id"]},
    )
    assert parent_child.status_code == 409
    assert parent_child.json()["error"]["code"] == "DEPENDENCY_SCOPE"

    dependency_id = hierarchy.json()["id"]
    removed = client.delete(f"/api/dependencies/{child['id']}/{dependency_id}")
    assert removed.status_code == 204
    assert client.get(f"/api/dependencies/{child['id']}").json()["depends_on"] == []
