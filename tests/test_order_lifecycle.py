from pathlib import Path

import yaml

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


def test_complete_order_lifecycle_example_compiles(tmp_path: Path) -> None:
    contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
    definition = ScenarioDefinition.model_validate(
        yaml.safe_load(Path("examples/order-lifecycle/scenario.yaml").read_text())
    )
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Order lifecycle example", contract)

    service.configure_scenario(simulation.id, "order-lifecycle", definition)
    compiled = service.compile_scenario(simulation.id, "order-lifecycle")
    mappings = service.repository.read_json(
        simulation.id, "mappings/scenarios/order-lifecycle.json"
    )

    assert compiled.mapping_count == 6
    assert [mapping["requiredScenarioState"] for mapping in mappings] == [
        "NOT_CREATED",
        "PENDING",
        "PENDING",
        "PAID",
        "PAID",
        "SHIPPED",
    ]
    assert [mapping.get("newScenarioState") for mapping in mappings] == [
        "PENDING",
        None,
        "PAID",
        None,
        "SHIPPED",
        None,
    ]
