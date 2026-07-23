import os
from pathlib import Path

import pytest
import yaml

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.scenarios import wiremock_scenario_name
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


@pytest.mark.asyncio
async def test_order_lifecycle_against_real_wiremock(tmp_path: Path) -> None:
    if os.getenv("SIMULOOM_WIREMOCK_INTEGRATION") != "1":
        pytest.skip("Set SIMULOOM_WIREMOCK_INTEGRATION=1 to run this test")
    contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
    definition = ScenarioDefinition.model_validate(
        yaml.safe_load(Path("examples/order-lifecycle/scenario.yaml").read_text())
    )
    wiremock = WireMockClient("http://localhost:8080")
    assert await wiremock.health()

    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)
    simulation = service.create("WireMock Integration", contract)
    scenario_id = "order-lifecycle"
    scenario_name = wiremock_scenario_name(simulation.id, scenario_id)

    try:
        service.configure_scenario(simulation.id, scenario_id, definition)
        first = await service.deploy_scenario(simulation.id, scenario_id)
        second = await service.deploy_scenario(simulation.id, scenario_id)

        created = await wiremock.execute(
            "POST", "/orders", {"itemId": "ITEM-SYN-001", "quantity": 1}
        )
        pending = await wiremock.execute("GET", "/orders/ORD-SYN-001")
        paid = await wiremock.execute(
            "POST",
            "/orders/ORD-SYN-001/payment",
            {"paymentToken": "PAY-SYN-001"},
        )
        shipped = await wiremock.execute(
            "POST",
            "/orders/ORD-SYN-001/shipment",
            {"carrier": "SYNTHETIC-CARRIER"},
        )
        reset = await service.reset_scenario(simulation.id, scenario_id)

        service.compile(simulation.id)
        await service.deploy(simulation.id)
        report = await service.validate(
            simulation.id, max_dataset_cases=3, reset_runtime_state=True
        )

        assert first.deployed_mappings == second.deployed_mappings == 6
        assert created.body["status"] == "PENDING"
        assert pending.body["status"] == "PENDING"
        assert paid.body["status"] == "PAID"
        assert shipped.body["status"] == "SHIPPED"
        assert reset.current_state == "NOT_CREATED"
        assert await wiremock.scenario_state(scenario_name) == "SHIPPED"
        assert report.status == "passed"
        assert report.state_coverage.percentage == 100.0
        assert report.transition_coverage.percentage == 100.0
        assert report.transition_coverage.covered == 3
    finally:
        await wiremock.remove_scenario_mappings(scenario_name)


@pytest.mark.asyncio
async def test_constraint_edges_against_real_wiremock(tmp_path: Path) -> None:
    if os.getenv("SIMULOOM_WIREMOCK_INTEGRATION") != "1":
        pytest.skip("Set SIMULOOM_WIREMOCK_INTEGRATION=1 to run this test")
    contract = yaml.safe_load(Path("examples/constraint-validation/openapi.yaml").read_text())
    wiremock = WireMockClient("http://localhost:8080")
    assert await wiremock.health()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)
    simulation = service.create("Constraint Integration", contract)

    try:
        compiled = service.compile(simulation.id)
        await service.deploy(simulation.id, reset_existing=True)
        report = await service.validate(
            simulation.id,
            max_dataset_cases=3,
            reset_runtime_state=True,
            include_boundary_cases=True,
            include_negative_cases=True,
            max_edge_cases_per_operation=20,
        )

        assert compiled.edge_mapping_count >= 20
        assert report.status == "passed"
        assert report.boundary_coverage.percentage == 100.0
        assert report.negative_coverage.percentage == 100.0
    finally:
        await wiremock.deploy([], reset_existing=True)
