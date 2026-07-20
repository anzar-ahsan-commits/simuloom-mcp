from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app


def test_rest_contract_analysis() -> None:
    contract = yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())
    with TestClient(app) as client:
        response = client.post("/api/v1/contracts/analyze", json={"contract": contract})

    assert response.status_code == 200
    assert response.json()["title"] == "Synthetic Benefits Eligibility API"
    assert response.json()["operations"][0]["operation_id"] == "checkEligibility"


def test_rest_bundle_export_and_import(tmp_path: Path, monkeypatch) -> None:
    contract = yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())
    test_service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    monkeypatch.setattr("simuloom.api.routes.service", test_service)

    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/simulations",
            json={"name": "API Portable Demo", "contract": contract},
        )
        simulation_id = created.json()["id"]
        client.post(
            f"/api/v1/simulations/{simulation_id}/data",
            json={"records": 2, "seed": 17},
        )
        dataset = client.get(f"/api/v1/simulations/{simulation_id}/data")
        validation_plan = client.post(
            f"/api/v1/simulations/{simulation_id}/validation/plan",
            json={"max_dataset_cases": 1},
        )
        manifest = client.get(f"/api/v1/simulations/{simulation_id}/manifest")
        exported = client.get(f"/api/v1/simulations/{simulation_id}/export/bundle")
        imported = client.post(
            "/api/v1/simulations/import",
            files={"bundle": ("demo.simuloom.zip", exported.content, "application/zip")},
        )
    finally:
        client.close()

    assert created.status_code == 201
    assert dataset.status_code == 200
    assert dataset.json()["synthetic"] is True
    assert validation_plan.status_code == 200
    assert validation_plan.json()["case_count"] == 5
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/yaml")
    assert exported.status_code == 200
    assert imported.status_code == 201
    assert imported.json()["imported_dataset_records"] == 2
    assert imported.json()["simulation"]["id"] != simulation_id
