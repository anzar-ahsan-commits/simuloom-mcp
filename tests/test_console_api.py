from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app


def console_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), NativeRuntimeAdapter())


def test_contract_upload_and_simulation_listing(tmp_path: Path, monkeypatch) -> None:
    test_service = console_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    contract = Path("examples/order-lifecycle/openapi.yaml").read_bytes()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/simulations/from-contract",
            data={"name": "Console Order Demo"},
            files={"contract": ("openapi.yaml", contract, "application/yaml")},
        )
        listed = client.get("/api/v1/simulations")
        session = client.get("/api/v1/session")
    finally:
        client.close()

    assert created.status_code == 201
    assert listed.status_code == 200
    assert session.json() == {
        "subject": "local-development",
        "role": "admin",
        "authentication_enabled": False,
    }
    assert listed.json() == [
        {
            **created.json(),
            "active_profile": "normal",
            "scenario_count": 0,
            "has_dataset": False,
            "has_report": False,
        }
    ]


def test_contract_upload_rejects_invalid_and_oversized_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", console_service(tmp_path))
    client = TestClient(app)
    try:
        invalid = client.post(
            "/api/v1/simulations/from-contract",
            data={"name": "Invalid Contract"},
            files={"contract": ("openapi.yaml", b"- not\n- an\n- object", "application/yaml")},
        )
        oversized = client.post(
            "/api/v1/simulations/from-contract",
            data={"name": "Large Contract"},
            files={"contract": ("openapi.yaml", b"x" * (2 * 1024 * 1024 + 1))},
        )
    finally:
        client.close()

    assert invalid.status_code == 422
    assert oversized.status_code == 413


def test_simulation_summary_tracks_workspace_artifacts(tmp_path: Path, monkeypatch) -> None:
    test_service = console_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
    simulation = test_service.create("Summary Demo", contract)
    test_service.generate_data(simulation.id, 1, 12)
    test_service.repository.write_json(simulation.id, "reports/latest.json", {"status": "passed"})

    client = TestClient(app)
    try:
        summary = client.get("/api/v1/simulations").json()[0]
    finally:
        client.close()

    assert summary["has_dataset"] is True
    assert summary["has_report"] is True
    assert summary["operation_count"] == 4


def test_console_workflow_generate_compile_deploy_and_validate(tmp_path: Path, monkeypatch) -> None:
    test_service = console_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    contract = Path("examples/order-lifecycle/openapi.yaml").read_bytes()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/simulations/from-contract",
            data={"name": "Console Workflow"},
            files={"contract": ("openapi.yaml", contract, "application/yaml")},
        )
        simulation_id = created.json()["id"]
        generated = client.post(
            f"/api/v1/simulations/{simulation_id}/data", json={"records": 2, "seed": 1207}
        )
        compiled = client.post(f"/api/v1/simulations/{simulation_id}/compile")
        deployed = client.post(
            f"/api/v1/simulations/{simulation_id}/deploy", json={"reset_existing": False}
        )
        plan = client.post(
            f"/api/v1/simulations/{simulation_id}/validation/plan",
            json={"max_dataset_cases": 1},
        )
        validated = client.post(
            f"/api/v1/simulations/{simulation_id}/validate",
            json={"max_dataset_cases": 1, "reset_runtime_state": True},
        )
    finally:
        client.close()

    assert generated.status_code == 200
    assert compiled.status_code == 200
    assert deployed.status_code == 200
    assert plan.status_code == 200
    assert validated.status_code == 200
    assert validated.json()["status"] == "passed"
