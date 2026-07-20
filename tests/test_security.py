import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.audit import AuditLog
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import create_app
from simuloom.security import AccessController, Role, role_allows

API_KEYS = {
    "viewer-secret-123456": {"subject": "github-reviewer", "role": "viewer"},
    "operator-secret-123456": {"subject": "qa-engineer", "role": "operator"},
    "admin-secret-123456": {"subject": "platform-owner", "role": "admin"},
}


def test_access_controller_authenticates_and_orders_roles() -> None:
    controller = AccessController(True, json.dumps(API_KEYS))

    viewer = controller.authenticate({"authorization": "Bearer viewer-secret-123456"})
    operator = controller.authenticate({"x-api-key": "operator-secret-123456"})

    assert viewer is not None and viewer.role is Role.VIEWER
    assert operator is not None and operator.subject == "qa-engineer"
    assert controller.authenticate({"authorization": "Bearer wrong"}) is None
    assert role_allows(Role.ADMIN, Role.OPERATOR)
    assert not role_allows(Role.VIEWER, Role.OPERATOR)


def test_enabled_auth_requires_configured_keys() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        AccessController(True, "{}")


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "events.jsonl"
    audit = AuditLog(path, "audit-signing-secret")
    for request_id in ("request-1", "request-2"):
        audit.append(
            request_id=request_id,
            subject="qa-engineer",
            role="operator",
            key_id="key-123",
            method="POST",
            path="/api/v1/simulations",
            status_code=201,
            duration_ms=12.5,
            outcome="allowed",
        )

    assert audit.verify()["valid"] is True
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["subject"] = "someone-else"
    lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")

    verification = audit.verify()
    assert verification["valid"] is False
    assert verification["error_line"] == 1
    with pytest.raises(RuntimeError, match="integrity check failed"):
        AuditLog(path, "audit-signing-secret")


def test_rest_roles_and_audit_events(tmp_path: Path, monkeypatch) -> None:
    contract = yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())
    test_service = SimulationService(
        WorkspaceRepository(tmp_path / "simulations"),
        WireMockClient("http://wiremock.invalid"),
    )
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    controller = AccessController(True, json.dumps(API_KEYS))
    audit = AuditLog(tmp_path / "audit" / "events.jsonl", "audit-signing-secret")
    secured_app = create_app(controller, audit)
    client = TestClient(secured_app)
    try:
        health = client.get("/api/v1/health")
        unauthenticated = client.post("/api/v1/contracts/analyze", json={"contract": contract})
        mcp_unauthenticated = client.post("/mcp", follow_redirects=False)
        mcp_authenticated = client.post(
            "/mcp",
            headers={"Authorization": "Bearer viewer-secret-123456"},
            follow_redirects=False,
        )
        viewer_analysis = client.post(
            "/api/v1/contracts/analyze",
            json={"contract": contract},
            headers={
                "Authorization": "Bearer viewer-secret-123456",
                "X-Request-ID": "known-id",
            },
        )
        viewer_create = client.post(
            "/api/v1/simulations",
            json={"name": "Denied Demo", "contract": contract},
            headers={"X-API-Key": "viewer-secret-123456"},
        )
        operator_create = client.post(
            "/api/v1/simulations",
            json={"name": "Authorized Demo", "contract": contract},
            headers={"X-API-Key": "operator-secret-123456"},
        )
        reset_denied = client.post(
            f"/api/v1/simulations/{operator_create.json()['id']}/deploy",
            json={"reset_existing": True},
            headers={"X-API-Key": "operator-secret-123456"},
        )
        audit_response = client.get(
            "/api/v1/audit/events?limit=20",
            headers={"Authorization": "Bearer admin-secret-123456"},
        )
    finally:
        client.close()

    assert health.status_code == 200
    assert unauthenticated.status_code == 401
    assert mcp_unauthenticated.status_code == 401
    assert mcp_authenticated.status_code != 401
    assert viewer_analysis.status_code == 200
    assert viewer_analysis.headers["x-request-id"] == "known-id"
    assert viewer_create.status_code == 403
    assert operator_create.status_code == 201
    assert reset_denied.status_code == 403
    assert audit_response.status_code == 200
    assert len(audit_response.json()["events"]) >= 5
    assert audit.verify()["valid"] is True
    audit_text = audit.path.read_text()
    assert "viewer-secret-123456" not in audit_text
    assert "operator-secret-123456" not in audit_text
    assert "admin-secret-123456" not in audit_text
