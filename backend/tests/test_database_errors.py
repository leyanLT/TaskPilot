"""Database failure handling and transaction rollback tests."""

from __future__ import annotations

import pytest
from app.exceptions import DatabaseOperationError
from app.models import Task
from app.repositories.task_repository import TaskRepository
from app.schemas import TaskCreate
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError


def test_api_database_failure_is_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_add(self, task):
        raise SQLAlchemyError("secret database internals")

    monkeypatch.setattr(TaskRepository, "add", broken_add)
    response = client.post("/api/tasks", json={"title": "会失败"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "DATABASE_ERROR"
    assert "secret" not in response.text.lower()
    assert "traceback" not in response.text.lower()
    assert client.get("/api/tasks").json() == []


def test_service_rolls_back_after_commit_failure(
    app, client, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = app.state.session_factory()
    service = TaskService(session)

    def failing_commit() -> None:
        raise OperationalError("INSERT", {}, Exception("disk full"))

    monkeypatch.setattr(session, "commit", failing_commit)
    with pytest.raises(DatabaseOperationError):
        service.create_task(TaskCreate(title="事务失败"))
    monkeypatch.undo()

    # The session must be usable after the service's rollback.
    remaining = session.scalars(select(Task)).all()
    assert remaining == []
    generated = Task(title="回滚后可继续写入", description=None, due_at=None)
    service.repository.add(generated)
    session.commit()
    assert session.get(Task, generated.id) is not None
    session.close()
