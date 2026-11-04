"""API-level AI unavailable, timeout, and manual-mode fallback tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import openai
import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

from tests.conftest import make_settings


class FailingModel:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def bind_tools(self, tools):
        def fail(messages):
            raise self.error

        return RunnableLambda(fail)


@pytest.fixture
def configured_client(database_path: Path):
    app = create_app(make_settings(database_path, api_key="test-key-not-real"))
    with TestClient(app) as client:
        yield client


def test_missing_api_key_returns_503_and_manual_mode_still_works(
    client: TestClient,
) -> None:
    response = client.post("/api/assistant/messages", json={"message": "我有哪些任务？"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"

    manual = client.post("/api/tasks", json={"title": "手动创建仍然可用"})
    assert manual.status_code == 201
    assert client.get("/api/tasks").json()[0]["title"] == "手动创建仍然可用"


def test_model_timeout_returns_sanitized_504(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://example.test"))

    def build_failing_model(settings):
        return FailingModel(timeout)

    monkeypatch.setattr("app.agent.llm.build_chat_model", build_failing_model)
    response = configured_client.post("/api/assistant/messages", json={"message": "我有哪些任务？"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "AI_TIMEOUT"
    assert "test-key" not in response.text


def test_unexpected_model_error_returns_502_without_internals(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build_failing_model(settings):
        return FailingModel(RuntimeError("internal-secret-stack"))

    monkeypatch.setattr("app.agent.llm.build_chat_model", build_failing_model)
    response = configured_client.post("/api/assistant/messages", json={"message": "我有哪些任务？"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_UPSTREAM_ERROR"
    assert "internal-secret-stack" not in response.text
    assert "Traceback" not in response.text


def test_assistant_request_validation(configured_client: TestClient) -> None:
    empty = configured_client.post("/api/assistant/messages", json={"message": "  "})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "VALIDATION_ERROR"

    unsupported = configured_client.post(
        "/api/assistant/confirm",
        json={"action_id": "00000000-0000-0000-0000-000000000000", "confirm": "yes"},
    )
    assert unsupported.status_code == 422


def test_configured_health_does_not_leak_key(configured_client: TestClient) -> None:
    response = configured_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["agent_configured"] is True
    assert "test-key" not in response.text
