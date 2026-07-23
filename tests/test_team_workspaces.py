import json
from pathlib import Path

from fastapi.testclient import TestClient

from simuloom.core.platform_store import PlatformStore
from simuloom.main import create_app
from simuloom.security import AccessController


def test_workspace_membership_lifecycle(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    monkeypatch.setattr("simuloom.api.routes.platform_store", store)
    keys = {
        "admin-secret-123456": {"subject": "owner", "role": "admin"},
        "viewer-secret-123456": {"subject": "reader", "role": "viewer"},
    }
    client = TestClient(create_app(AccessController(True, json.dumps(keys))))
    try:
        created = client.post(
            "/api/v1/workspaces",
            json={"name": "Payments Team"},
            headers={"X-API-Key": "admin-secret-123456"},
        )
        workspace_id = created.json()["id"]
        invisible = client.get("/api/v1/workspaces", headers={"X-API-Key": "viewer-secret-123456"})
        added = client.put(
            f"/api/v1/workspaces/{workspace_id}/members/reader",
            json={"role": "viewer"},
            headers={"X-API-Key": "admin-secret-123456"},
        )
        visible = client.get("/api/v1/workspaces", headers={"X-API-Key": "viewer-secret-123456"})
        members = client.get(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers={"X-API-Key": "viewer-secret-123456"},
        )
        removed = client.delete(
            f"/api/v1/workspaces/{workspace_id}/members/reader",
            headers={"X-API-Key": "admin-secret-123456"},
        )
        last_admin = client.delete(
            f"/api/v1/workspaces/{workspace_id}/members/owner",
            headers={"X-API-Key": "admin-secret-123456"},
        )
    finally:
        client.close()

    assert created.status_code == 201
    assert invisible.json() == []
    assert added.status_code == 200
    assert [item["id"] for item in visible.json()] == [workspace_id]
    assert {item["subject"] for item in members.json()} == {"owner", "reader"}
    assert removed.status_code == 204
    assert last_admin.status_code == 409
