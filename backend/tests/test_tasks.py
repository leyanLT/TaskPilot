"""Task CRUD, validation, filtering, sorting, and persistence tests."""

from __future__ import annotations

from pathlib import Path

from app.main import create_app
from fastapi.testclient import TestClient

from tests.conftest import make_settings


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_health_and_openapi(client: TestClient) -> None:
    health_response = client.get("/api/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert "deepseek" not in health_response.text.lower()

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/api/tasks" in paths
    assert "/api/tasks/{task_id}" in paths
    assert "/api/assistant/messages" in paths
    assert "/api/assistant/confirm" in paths


def test_create_task_with_all_fields(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={
            "title": "  完成实验报告  ",
            "description": "  汇总实验结果  ",
            "due_at": "2026-11-04T15:00:00+08:00",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "完成实验报告"
    assert body["description"] == "汇总实验结果"
    assert body["status"] == "pending"
    assert body["due_at"] == "2026-11-04T07:00:00+00:00"
    assert body["created_at"].endswith("+00:00")
    assert body["updated_at"].endswith("+00:00")
    assert body["id"]


def test_create_task_minimal_defaults(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"title": "最小任务"})
    assert response.status_code == 201
    body = response.json()
    assert body["description"] is None
    assert body["due_at"] is None
    assert body["status"] == "pending"


def test_list_returns_persisted_tasks(client: TestClient, create_task) -> None:
    first = create_task(title="任务一")
    second = create_task(title="任务二")
    response = client.get("/api/tasks")
    assert response.status_code == 200
    ids = {task["id"] for task in response.json()}
    assert ids == {first["id"], second["id"]}


def test_task_filter_by_status(client: TestClient, create_task) -> None:
    pending = create_task(title="待办")
    completed = create_task(title="已办")
    client.patch(f"/api/tasks/{completed['id']}", json={"status": "completed"})

    pending_response = client.get("/api/tasks?status=pending")
    completed_response = client.get("/api/tasks?status=completed")
    assert [task["id"] for task in pending_response.json()] == [pending["id"]]
    assert [task["id"] for task in completed_response.json()] == [completed["id"]]


def test_task_sorting_created_and_due_dates(client: TestClient, create_task) -> None:
    first = create_task(title="无截止", due_at=None)
    second = create_task(title="晚截止", due_at="2026-11-10T09:00:00+08:00")
    third = create_task(title="早截止", due_at="2026-11-05T09:00:00+08:00")

    created_asc = client.get("/api/tasks?sort_by=created_at&order=asc").json()
    assert [task["id"] for task in created_asc] == [first["id"], second["id"], third["id"]]

    due_asc = client.get("/api/tasks?sort_by=due_at&order=asc").json()
    assert [task["id"] for task in due_asc] == [third["id"], second["id"], first["id"]]

    due_desc = client.get("/api/tasks?sort_by=due_at&order=desc").json()
    assert [task["id"] for task in due_desc] == [second["id"], third["id"], first["id"]]


def test_get_task_detail(client: TestClient, create_task) -> None:
    created = create_task(title="详情任务")
    response = client.get(f"/api/tasks/{created['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "详情任务"


def test_get_missing_task_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert error_code(response) == "TASK_NOT_FOUND"
    assert "Traceback" not in response.text


def test_edit_task_and_other_task_unaffected(client: TestClient, create_task) -> None:
    edited = create_task(title="待编辑", description="旧描述")
    untouched = create_task(title="不应变化", description="原描述")
    response = client.patch(
        f"/api/tasks/{edited['id']}",
        json={
            "title": "  已编辑  ",
            "description": "新描述",
            "due_at": "2026-12-01T10:00:00+08:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "已编辑"
    assert body["description"] == "新描述"
    assert body["due_at"] == "2026-12-01T02:00:00+00:00"

    other = client.get(f"/api/tasks/{untouched['id']}").json()
    assert other["title"] == "不应变化"
    assert other["description"] == "原描述"
    assert other["due_at"] is None


def test_edit_can_clear_optional_fields(client: TestClient, create_task) -> None:
    task = create_task(
        title="清空字段",
        description="可清空",
        due_at="2026-12-01T10:00:00+08:00",
    )
    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"description": None, "due_at": None},
    )
    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["due_at"] is None


def test_edit_missing_task_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/api/tasks/00000000-0000-0000-0000-000000000000",
        json={"title": "不存在"},
    )
    assert response.status_code == 404
    assert error_code(response) == "TASK_NOT_FOUND"


def test_status_toggle_is_consistent_and_idempotent(client: TestClient, create_task) -> None:
    task = create_task()
    completed = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    again = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert again.status_code == 200
    assert again.json()["status"] == "completed"
    pending = client.patch(f"/api/tasks/{task['id']}", json={"status": "pending"})
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "pending"


def test_delete_task_and_missing_errors(client: TestClient, create_task) -> None:
    task = create_task()
    first_delete = client.delete(f"/api/tasks/{task['id']}")
    assert first_delete.status_code == 204
    assert first_delete.content == b""
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404
    second_delete = client.delete(f"/api/tasks/{task['id']}")
    assert second_delete.status_code == 404
    assert error_code(second_delete) == "TASK_NOT_FOUND"


def test_validation_errors_are_structured(client: TestClient) -> None:
    cases = [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 101},
        {"title": "合法", "description": "x" * 501},
        {"title": "合法", "due_at": "2026-11-04T15:00:00"},
        {"title": "合法", "unknown": "field"},
    ]
    for payload in cases:
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 422, payload
        assert error_code(response) == "VALIDATION_ERROR"
        assert isinstance(response.json()["error"]["details"], list)

    missing_timezone = client.post(
        "/api/tasks",
        json={"title": "合法", "due_at": "2026-11-04T15:00:00"},
    )
    assert missing_timezone.status_code == 422
    assert "时区" in missing_timezone.text


def test_validation_boundaries_are_inclusive(client: TestClient) -> None:
    max_title = "字" * 100
    max_description = "描" * 500
    response = client.post(
        "/api/tasks",
        json={"title": max_title, "description": max_description},
    )
    assert response.status_code == 201
    assert response.json()["title"] == max_title
    assert response.json()["description"] == max_description


def test_update_validation_errors(client: TestClient, create_task) -> None:
    task = create_task()
    cases = [
        {},
        {"title": None},
        {"title": ""},
        {"status": "invalid"},
        {"unknown": "field"},
        {"description": "x" * 501},
        {"due_at": "2026-11-04T15:00:00"},
    ]
    for payload in cases:
        response = client.patch(f"/api/tasks/{task['id']}", json=payload)
        assert response.status_code == 422, payload
        assert error_code(response) == "VALIDATION_ERROR"


def test_invalid_uuid_returns_validation_error(client: TestClient) -> None:
    response = client.get("/api/tasks/not-a-uuid")
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_unknown_api_route_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_tasks_persist_across_app_restarts(database_path: Path) -> None:
    settings = make_settings(database_path)
    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        response = first_client.post(
            "/api/tasks",
            json={"title": "重启后仍然存在", "due_at": "2026-12-01T10:00:00+08:00"},
        )
        assert response.status_code == 201
        task_id = response.json()["id"]

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        persisted = second_client.get(f"/api/tasks/{task_id}")
        assert persisted.status_code == 200
        assert persisted.json()["title"] == "重启后仍然存在"
        assert persisted.json()["status"] == "pending"
