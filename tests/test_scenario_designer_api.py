from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.scenario_graph import scenario_graph_diagnostics
from simuloom.core.service import SimulationService
from simuloom.main import app
from simuloom.models import ScenarioDefinition


def designer_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), NativeRuntimeAdapter())


def test_designer_lists_contract_operations_scenarios_and_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    test_service = designer_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", test_service)
    contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
    scenario = yaml.safe_load(Path("examples/order-lifecycle/scenario.yaml").read_text())
    simulation = test_service.create("Designer Demo", contract)

    client = TestClient(app)
    try:
        configured = client.put(
            f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle",
            json=scenario,
        )
        operations = client.get(f"/api/v1/simulations/{simulation.id}/operations")
        scenarios = client.get(f"/api/v1/simulations/{simulation.id}/scenarios")
        diagnostics = client.get(
            f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle/diagnostics"
        )
    finally:
        client.close()

    assert configured.status_code == 200
    assert operations.status_code == 200
    assert {item["operation_id"] for item in operations.json()} == {
        "createOrder",
        "getOrder",
        "payOrder",
        "shipOrder",
    }
    assert scenarios.json()[0] == {
        "simulation_id": simulation.id,
        "scenario_id": "order-lifecycle",
        "name": "Order lifecycle",
        "description": scenario["description"],
        "initial_state": "NOT_CREATED",
        "reset_state": "NOT_CREATED",
        "state_count": 4,
        "handler_count": 6,
        "warning_count": 0,
    }
    assert {item["code"] for item in diagnostics.json()} == {"terminal-state"}


def test_graph_diagnostics_find_unreachable_terminal_and_self_transition() -> None:
    definition = ScenarioDefinition.model_validate(
        {
            "name": "Diagnostic graph",
            "description": "Exercises designer graph diagnostics",
            "initial_state": "STARTED",
            "states": [
                {
                    "name": "STARTED",
                    "handlers": [
                        {
                            "name": "repeat",
                            "request": {"method": "GET", "path": "/repeat"},
                            "response": {"status": 200, "json_body": {"ok": True}},
                            "new_state": "STARTED",
                        }
                    ],
                },
                {
                    "name": "ORPHANED",
                    "handlers": [
                        {
                            "name": "inspect orphan",
                            "request": {"method": "GET", "path": "/orphaned"},
                            "response": {"status": 200, "json_body": {"ok": False}},
                        }
                    ],
                },
            ],
        }
    )

    diagnostics = scenario_graph_diagnostics(definition)

    assert {(item.code, item.state) for item in diagnostics} == {
        ("self-transition", "STARTED"),
        ("unreachable-state", "ORPHANED"),
        ("terminal-state", "ORPHANED"),
    }


def test_designer_endpoints_return_not_found_for_unknown_simulation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", designer_service(tmp_path))
    client = TestClient(app)
    try:
        operations = client.get("/api/v1/simulations/missing/operations")
        scenarios = client.get("/api/v1/simulations/missing/scenarios")
    finally:
        client.close()

    assert operations.status_code == 404
    assert scenarios.status_code == 404
