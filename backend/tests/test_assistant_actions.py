"""Pending-action confirmation, cancellation, idempotency, and expiry tests."""

from __future__ import annotations

from datetime import timedelta

from app.database import utc_now
from app.models import PendingAction, Task
from app.schemas import TaskCreate
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from sqlalchemy import update


def test_ai_create_requires_confirmation(
    client: TestClient,
    action_service: PendingActionService,
    task_service: TaskService,
) -> None:
    action = action_service.create_task_draft(
        TaskCreate(title="AI 草稿任务", description="等待确认")
    )
    assert action.status == "pending"
    assert client.get("/api/tasks").json() == []
    assert task_service.list_tasks() == []

    response = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["task"]["title"] == "AI 草稿任务"
    assert body["task"]["status"] == "pending"
    assert len(client.get("/api/tasks").json()) == 1


def test_repeated_confirmation_creates_only_one_task(
    client: TestClient,
    action_service: PendingActionService,
) -> None:
    action = action_service.create_task_draft(TaskCreate(title="只创建一次"))
    first = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    second = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1


def test_cancel_has_no_side_effects_and_is_idempotent(
    client: TestClient,
    action_service: PendingActionService,
) -> None:
    action = action_service.create_task_draft(TaskCreate(title="取消创建"))
    first = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": False},
    )
    second = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": False},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"
    assert client.get("/api/tasks").json() == []

    confirm_after_cancel = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert confirm_after_cancel.status_code == 409
    assert confirm_after_cancel.json()["error"]["code"] == "ACTION_CONFLICT"


def test_cancel_after_confirmation_is_rejected(
    client: TestClient,
    action_service: PendingActionService,
) -> None:
    action = action_service.create_task_draft(TaskCreate(title="执行后不可取消"))
    client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    response = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": False},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTION_CONFLICT"


def test_expired_action_cannot_execute(
    client: TestClient,
    session,
    action_service: PendingActionService,
) -> None:
    action = action_service.create_task_draft(TaskCreate(title="过期任务"))
    session.execute(
        update(PendingAction)
        .where(PendingAction.id == action.id)
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    session.commit()

    response = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "ACTION_EXPIRED"
    assert client.get("/api/tasks").json() == []


def test_missing_action_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/assistant/confirm",
        json={
            "action_id": "00000000-0000-0000-0000-000000000000",
            "confirm": True,
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACTION_NOT_FOUND"


def test_confirm_payload_validation(client: TestClient) -> None:
    invalid_uuid = client.post(
        "/api/assistant/confirm",
        json={"action_id": "nope", "confirm": True},
    )
    assert invalid_uuid.status_code == 422
    assert invalid_uuid.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_confirm = client.post(
        "/api/assistant/confirm",
        json={"action_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing_confirm.status_code == 422


def test_complete_action_requires_confirmation_and_is_idempotent(
    client: TestClient,
    action_service: PendingActionService,
    create_task,
) -> None:
    created = create_task(title="完成我")
    task = action_service.task_service.get_task(created["id"])
    action = action_service.create_completion_draft(task)
    assert action.action_type == "complete_task"
    assert client.get(f"/api/tasks/{created['id']}").json()["status"] == "pending"

    first = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    second = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "confirmed"
    assert first.json()["task"]["status"] == "completed"
    assert second.status_code == 200
    assert second.json()["task"]["status"] == "completed"
    assert client.get(f"/api/tasks/{created['id']}").json()["status"] == "completed"


def test_completion_action_for_already_completed_task_is_rejected(
    client: TestClient,
    action_service: PendingActionService,
    create_task,
) -> None:
    created = create_task(title="已完成任务")
    client.patch(f"/api/tasks/{created['id']}", json={"status": "completed"})
    task = action_service.task_service.get_task(created["id"])
    from app.exceptions import TaskAlreadyCompletedError

    try:
        action_service.create_completion_draft(task)
    except TaskAlreadyCompletedError as exc:
        assert exc.code == "TASK_ALREADY_COMPLETED"
    else:
        raise AssertionError("expected TaskAlreadyCompletedError")


def test_confirming_action_for_deleted_task_keeps_action_pending(
    client: TestClient,
    session,
    action_service: PendingActionService,
    create_task,
) -> None:
    created = create_task(title="确认前删除")
    task = action_service.task_service.get_task(created["id"])
    action = action_service.create_completion_draft(task)
    client.delete(f"/api/tasks/{created['id']}")

    response = client.post(
        "/api/assistant/confirm",
        json={"action_id": action.id, "confirm": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"

    session.expire_all()
    persisted = session.get(PendingAction, action.id)
    assert persisted is not None
    assert persisted.status == "pending"
    assert session.get(Task, created["id"]) is None
