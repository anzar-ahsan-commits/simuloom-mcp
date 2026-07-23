from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app


def native_service(tmp_path: Path) -> SimulationService:
    return SimulationService(
        WorkspaceRepository(tmp_path),
        NativeRuntimeAdapter("http://localhost:8000/runtime"),
    )


def test_native_runtime_order_lifecycle_over_http(tmp_path: Path, monkeypatch) -> None:
    service = native_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", service)
    monkeypatch.setattr("simuloom.api.runtime.service", service)
    contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
    scenario = yaml.safe_load(Path("examples/order-lifecycle/scenario.yaml").read_text())
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/simulations",
            json={"name": "Native Lifecycle", "contract": contract},
        )
        simulation_id = created.json()["id"]
        configured = client.put(
            f"/api/v1/simulations/{simulation_id}/scenarios/order-lifecycle",
            json=scenario,
        )
        deployed = client.post(
            f"/api/v1/simulations/{simulation_id}/scenarios/order-lifecycle/deploy"
        )

        base = f"/runtime/{simulation_id}"
        order = client.post(f"{base}/orders", json={"itemId": "ITEM-SYN-001", "quantity": 1})
        pending = client.get(f"{base}/orders/ORD-SYN-001")
        paid = client.post(
            f"{base}/orders/ORD-SYN-001/payment",
            json={"paymentToken": "PAY-SYN-001"},
        )
        shipped = client.post(
            f"{base}/orders/ORD-SYN-001/shipment",
            json={"carrier": "SYNTHETIC-CARRIER"},
        )
        reset = client.post(f"/api/v1/simulations/{simulation_id}/scenarios/order-lifecycle/reset")
        capabilities = client.get("/api/v1/runtime")
    finally:
        client.close()

    assert created.status_code == 201
    assert configured.status_code == 200
    assert deployed.status_code == 200
    assert [order.json()["status"], pending.json()["status"]] == ["PENDING", "PENDING"]
    assert paid.json()["status"] == "PAID"
    assert shipped.json()["status"] == "SHIPPED"
    assert reset.json()["current_state"] == "NOT_CREATED"
    assert capabilities.json()["runtime"] == "native"


def test_native_runtime_pairwise_validation(tmp_path: Path, monkeypatch) -> None:
    service = native_service(tmp_path)
    monkeypatch.setattr("simuloom.api.routes.service", service)
    monkeypatch.setattr("simuloom.api.runtime.service", service)
    contract = yaml.safe_load(Path("examples/pricing-checkout/openapi.yaml").read_text())
    simulation = service.create("Native Pairwise", contract)
    service.compile(simulation.id)

    client = TestClient(app)
    try:
        deployed = client.post(
            f"/api/v1/simulations/{simulation.id}/deploy",
            json={"reset_existing": False},
        )
        validated = client.post(
            f"/api/v1/simulations/{simulation.id}/validate",
            json={
                "max_dataset_cases": 3,
                "reset_runtime_state": True,
                "include_pairwise_cases": True,
                "max_pairwise_cases_per_operation": 50,
            },
        )
    finally:
        client.close()

    assert deployed.status_code == 200
    assert validated.status_code == 200
    assert validated.json()["status"] == "passed"
    assert validated.json()["pairwise_coverage"]["percentage"] == 100.0
