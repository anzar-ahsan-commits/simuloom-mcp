import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from test_scenarios import contract

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.ai_assistant import ScenarioAIAssistant
from simuloom.core.platform_store import PlatformStore
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import create_app
from simuloom.security import AccessController


def test_ai_chat_persists_grounded_messages_and_requires_action_approval(
    tmp_path: Path, monkeypatch
) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    test_service = SimulationService(
        WorkspaceRepository(tmp_path / "workspace"), WireMockClient("http://wiremock.invalid")
    )
    simulation = test_service.create("Chat order API", contract())

    def respond(_: httpx.Request) -> httpx.Response:
        completion = {
            "answer": "This contract can be compiled into deterministic mappings.",
            "actions": [
                {
                    "kind": "compile",
                    "arguments": {},
                    "summary": "Compile the selected simulation",
                    "risk": "medium",
                }
            ],
            "suggested_prompts": ["Explain the available operations"],
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(completion)}})

    assistant = ScenarioAIAssistant(
        True, "http://ollama:11434", "test-model", httpx.MockTransport(respond)
    )
    monkeypatch.setattr("simuloom.api.routes.platform_store", store)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    monkeypatch.setattr("simuloom.api.routes.ai_assistant", assistant)
    keys = {
        "operator-secret-123456": {"subject": "operator", "role": "operator"},
        "viewer-secret-12345678": {"subject": "viewer", "role": "viewer"},
    }
    client = TestClient(create_app(AccessController(True, json.dumps(keys))))
    operator = {"X-API-Key": "operator-secret-123456"}
    viewer = {"X-API-Key": "viewer-secret-12345678"}
    try:
        created = client.post(
            "/api/v1/ai/chat/threads",
            json={"simulation_id": simulation.id, "title": "Release readiness"},
            headers=operator,
        )
        thread_id = created.json()["id"]
        message = client.post(
            f"/api/v1/ai/chat/threads/{thread_id}/messages",
            json={"content": "Can this simulation be compiled now?"},
            headers=operator,
        )
        action_id = message.json()["actions"][0]["id"]
        hidden = client.get(f"/api/v1/ai/chat/threads/{thread_id}", headers=viewer)
        denied = client.post(f"/api/v1/ai/chat/actions/{action_id}/approve", headers=viewer)
        approved = client.post(f"/api/v1/ai/chat/actions/{action_id}/approve", headers=operator)
        replayed = client.post(f"/api/v1/ai/chat/actions/{action_id}/approve", headers=operator)
        thread = client.get(f"/api/v1/ai/chat/threads/{thread_id}", headers=operator)
    finally:
        client.close()

    assert created.status_code == 201
    assert message.status_code == 201
    assert message.json()["actions"][0]["status"] == "proposed"
    assert hidden.status_code == 404
    assert denied.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert approved.json()["result"]["simulation_id"] == simulation.id
    assert replayed.status_code == 409
    assert len(thread.json()["messages"]) == 2


def test_ai_chat_is_disabled_without_opt_in(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    test_service = SimulationService(
        WorkspaceRepository(tmp_path / "workspace"), WireMockClient("http://wiremock.invalid")
    )
    simulation = test_service.create("Disabled AI API", contract())
    monkeypatch.setattr("simuloom.api.routes.platform_store", store)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    monkeypatch.setattr(
        "simuloom.api.routes.ai_assistant",
        ScenarioAIAssistant(False, "http://localhost:11434", "disabled"),
    )
    client = TestClient(create_app())
    try:
        created = client.post(
            "/api/v1/ai/chat/threads",
            json={"simulation_id": simulation.id, "title": "Disabled assistant"},
        )
        response = client.post(
            f"/api/v1/ai/chat/threads/{created.json()['id']}/messages",
            json={"content": "Explain this simulation"},
        )
    finally:
        client.close()

    assert response.status_code == 503


def test_admin_can_persist_ai_enablement_from_rest(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    assistant = ScenarioAIAssistant(False, "http://ollama:11434", "local-model")
    monkeypatch.setattr("simuloom.api.routes.platform_store", store)
    monkeypatch.setattr("simuloom.api.routes.ai_assistant", assistant)
    keys = {
        "admin-secret-1234567": {"subject": "admin", "role": "admin"},
        "viewer-secret-123456": {"subject": "viewer", "role": "viewer"},
    }
    client = TestClient(create_app(AccessController(True, json.dumps(keys))))
    admin = {"X-API-Key": "admin-secret-1234567"}
    viewer = {"X-API-Key": "viewer-secret-123456"}
    try:
        initial = client.get("/api/v1/ai/settings", headers=viewer)
        denied = client.put("/api/v1/ai/settings", json={"enabled": True}, headers=viewer)
        enabled = client.put("/api/v1/ai/settings", json={"enabled": True}, headers=admin)
    finally:
        client.close()

    assert initial.json()["enabled"] is False
    assert denied.status_code == 403
    assert enabled.status_code == 200
    assert enabled.json() == {
        "enabled": True,
        "provider": "ollama",
        "model": "local-model",
        "base_url": "http://ollama:11434",
        "persisted": True,
    }
    assert assistant.enabled is True
    assert store.get_setting("ai.enabled") == "true"
