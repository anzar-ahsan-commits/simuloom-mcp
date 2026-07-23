from pathlib import Path

import pytest
from test_scenarios import ScenarioWireMock, contract, definition_payload

from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


@pytest.mark.asyncio
async def test_low_cardinality_metrics_cover_scenario_operations(tmp_path: Path) -> None:
    service = SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]
    simulation = service.create("Metrics", contract())
    service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    await service.deploy_scenario(simulation.id, "order-lifecycle")
    await service.publish_scenario_event(simulation.id, "unmatched", None, "operator")

    snapshot = service.metrics_snapshot()
    prometheus = service.prometheus_metrics()

    assert snapshot == {
        "scenario_deployments_total": 1,
        "scenario_events_total": 1,
        "scenario_saves_total": 1,
    }
    assert "simuloom_scenario_deployments_total 1" in prometheus
    assert "simulation_id" not in prometheus
