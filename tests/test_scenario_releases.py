import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_scenarios import ScenarioWireMock, contract, definition_payload

from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app
from simuloom.models import ScenarioDefinition
from simuloom.security import Principal, Role, _current_principal


@pytest.fixture
def release_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]


def test_release_rest_endpoints(release_service: SimulationService, monkeypatch) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", release_service)
    simulation = release_service.create("REST releases", contract())
    release_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    base = f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle"
    client = TestClient(app)
    try:
        deployed = client.post(f"{base}/history/1/deploy")
        releases = client.get(f"{base}/releases")
        release = client.get(f"{base}/releases/1")
        rollback = client.post(f"{base}/releases/1/rollback")
        missing = client.get(f"{base}/releases/99")
    finally:
        client.close()

    assert deployed.status_code == 200
    assert deployed.json()["release_number"] == 1
    assert releases.json()[0]["revision"] == 1
    assert release.json()["mapping_fingerprint"] == deployed.json()["mapping_fingerprint"]
    assert rollback.json()["release_number"] == 2
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_release_mcp_tools_and_resource(
    release_service: SimulationService, monkeypatch
) -> None:
    from simuloom.mcp import server as mcp_server

    monkeypatch.setattr(mcp_server, "service", release_service)
    simulation = release_service.create("MCP releases", contract())
    release_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    token = _current_principal.set(Principal("mcp-releaser", Role.OPERATOR, None))
    try:
        deployed = await mcp_server.deploy_scenario(simulation.id, "order-lifecycle", revision=1)
        releases = mcp_server.scenario_releases(simulation.id, "order-lifecycle")
        resource = json.loads(mcp_server.scenario_release_history(simulation.id, "order-lifecycle"))
        rollback = await mcp_server.rollback_scenario_release(simulation.id, "order-lifecycle", 1)
    finally:
        _current_principal.reset(token)

    assert deployed["deployed_by"] == "mcp-releaser"
    assert releases == resource
    assert rollback["release_number"] == 2
    assert rollback["revision"] == 1


@pytest.mark.asyncio
async def test_failed_runtime_deployment_does_not_record_release(tmp_path: Path) -> None:
    class FailingRuntime(ScenarioWireMock):
        async def deploy_scenario(self, *args, **kwargs) -> int:
            raise RuntimeError("runtime rejected mappings")

    service = SimulationService(WorkspaceRepository(tmp_path), FailingRuntime())  # type: ignore[arg-type]
    simulation = service.create("Failed release", contract())
    service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )

    with pytest.raises(RuntimeError, match="rejected"):
        await service.deploy_scenario(simulation.id, "order-lifecycle")

    assert service.scenario_releases(simulation.id, "order-lifecycle") == []
