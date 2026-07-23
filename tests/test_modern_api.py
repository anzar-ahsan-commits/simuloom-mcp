import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from simuloom.core.integrations import IntegrationDispatcher
from simuloom.core.platform_store import PlatformStore
from simuloom.core.secrets import SecretVault
from simuloom.main import create_app
from simuloom.security import AccessController


def test_modern_platform_rest_workflow(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    vault = SecretVault("test-master-key-with-at-least-32-characters")
    dispatcher = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "integration-signing-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(202)),
    )
    monkeypatch.setattr("simuloom.api.routes.platform_store", store)
    monkeypatch.setattr("simuloom.api.routes.secret_vault", vault)
    monkeypatch.setattr("simuloom.api.routes.integration_dispatcher", dispatcher)
    keys = {
        "admin-secret-123456": {"subject": "owner", "role": "admin"},
    }
    client = TestClient(create_app(AccessController(True, json.dumps(keys))))
    headers = {"X-API-Key": "admin-secret-123456"}
    try:
        workspace = client.post(
            "/api/v1/workspaces", json={"name": "Modern Platform"}, headers=headers
        )
        workspace_id = workspace.json()["id"]
        secret = client.put(
            f"/api/v1/workspaces/{workspace_id}/secrets/WEBHOOK_TOKEN",
            json={"value": "not-returned"},
            headers=headers,
        )
        integration = client.post(
            f"/api/v1/workspaces/{workspace_id}/integrations",
            json={
                "name": "Deployment events",
                "endpoint": "https://hooks.example.com/simuloom",
                "event_types": ["scenario.deployed"],
            },
            headers=headers,
        )
        delivery = client.post(
            f"/api/v1/workspaces/{workspace_id}/integrations/{integration.json()['id']}/dispatch",
            json={"event_type": "scenario.deployed", "payload": {"synthetic": True}},
            headers=headers,
        )
        queued = client.post(
            "/api/v1/jobs",
            json={"workspace_id": workspace_id, "kind": "workspace-backup"},
            headers=headers,
        )
        completed = client.get(f"/api/v1/jobs/{queued.json()['id']}", headers=headers)
    finally:
        client.close()

    assert workspace.status_code == 201
    assert secret.status_code == 200
    assert "value" not in secret.json()
    assert integration.status_code == 201
    assert delivery.json()["accepted"] is True
    assert delivery.json()["attempts"] == 1
    assert queued.status_code == 202
    assert completed.json()["status"] == "succeeded"
