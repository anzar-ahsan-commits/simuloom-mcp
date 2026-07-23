from pathlib import Path

from fastapi.testclient import TestClient

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app


def test_readiness_reports_workspace_and_runtime(tmp_path: Path, monkeypatch) -> None:
    test_service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    monkeypatch.setattr("simuloom.api.routes.service", test_service)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/readiness")
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "runtime": "wiremock",
        "runtime_ready": False,
        "workspace_format": "simuloom-workspace",
        "workspace_schema_version": 1,
        "supported_workspace_schema_version": 1,
        "workspace_writable": True,
        "simulation_count": 0,
        "platform_store_ready": True,
        "platform_schema_version": 4,
        "supported_platform_schema_version": 4,
    }
