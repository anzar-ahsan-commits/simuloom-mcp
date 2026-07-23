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
def promotion_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]


def test_promotes_exact_revision_and_revalidates_target_contract(
    promotion_service: SimulationService,
) -> None:
    source = promotion_service.create("Development", contract())
    target = promotion_service.create("Staging", contract())
    incompatible = promotion_service.create(
        "Incompatible",
        {
            "openapi": "3.1.0",
            "info": {"title": "Other", "version": "1"},
            "paths": {
                "/other": {
                    "get": {
                        "operationId": "other",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        },
    )
    promotion_service.configure_scenario(
        source.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )

    promoted = promotion_service.promote_scenario_revision(
        source.id, "order-lifecycle", 1, target.id, None, "promoter"
    )

    assert promoted.target_revision == 1
    assert (
        promotion_service.get_scenario(target.id, "order-lifecycle").definition.name
        == "Order lifecycle"
    )
    with pytest.raises(ValueError, match="does not match"):
        promotion_service.promote_scenario_revision(
            source.id, "order-lifecycle", 1, incompatible.id, None, "promoter"
        )


def test_promotion_rest_and_mcp(promotion_service: SimulationService, monkeypatch) -> None:
    from simuloom.mcp import server as mcp_server

    monkeypatch.setattr("simuloom.api.routes.service", promotion_service)
    monkeypatch.setattr(mcp_server, "service", promotion_service)
    source = promotion_service.create("REST source", contract())
    rest_target = promotion_service.create("REST target", contract())
    mcp_target = promotion_service.create("MCP target", contract())
    promotion_service.configure_scenario(
        source.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    path = f"/api/v1/simulations/{source.id}/scenarios/order-lifecycle/history/1/promote"
    client = TestClient(app)
    try:
        response = client.post(path, json={"target_simulation_id": rest_target.id})
    finally:
        client.close()
    token = _current_principal.set(Principal("mcp-promoter", Role.OPERATOR, None))
    try:
        mcp_result = mcp_server.promote_scenario_revision(
            source.id, "order-lifecycle", 1, mcp_target.id
        )
    finally:
        _current_principal.reset(token)

    assert response.status_code == 200
    assert response.json()["status"] == "promoted"
    assert mcp_result["promoted_by"] == "mcp-promoter"
