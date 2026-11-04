"""Shared backend test fixtures with an isolated SQLite database."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from app.config import Settings
from app.main import create_app
from app.services.pending_action_service import PendingActionService
from app.services.task_service import TaskService
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "taskpilot-test.db"


def make_settings(database_path: Path, *, api_key: str = "") -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        database_auto_migrate=False,
        deepseek_api_key=api_key,
        app_timezone="Asia/Shanghai",
        agent_timeout_seconds=5,
        agent_max_retries=0,
        pending_action_ttl_minutes=30,
    )


@pytest.fixture
def settings(database_path: Path) -> Settings:
    return make_settings(database_path)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(app, client) -> Iterator[Session]:
    db_session = app.state.session_factory()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture
def task_service(session: Session) -> TaskService:
    return TaskService(session)


@pytest.fixture
def action_service(session: Session, task_service: TaskService) -> PendingActionService:
    return PendingActionService(session, task_service, ttl_minutes=30)


@pytest.fixture
def create_task(client: TestClient) -> Callable[..., dict]:
    def _create(**overrides: object) -> dict:
        payload = {"title": overrides.pop("title", "测试任务")}
        payload.update(overrides)
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _create
