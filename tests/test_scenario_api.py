import json

import pytest
from fastapi.testclient import TestClient

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app
from simuloom.security import Principal, Role, _current_principal


def contract() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Orders", "version": "1"},
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "responses": {"201": {"description": "created"}},
                }
            },
            "/orders/{orderId}": {
                "get": {
                    "operationId": "getOrder",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }


def scenario_payload() -> dict:
    return {
        "name": "Order lifecycle",
        "description": "Create and inspect",
        "initial_state": "NEW",
        "states": [
            {
                "name": "NEW",
                "handlers": [
                    {
                        "name": "create",
                        "request": {"method": "POST", "path": "/orders"},
                        "response": {"status": 201, "json_body": {"status": "PENDING"}},
                        "new_state": "PENDING",
                    }
                ],
            },
            {
                "name": "PENDING",
                "handlers": [
                    {
                        "name": "inspect",
                        "request": {"method": "GET", "path": "/orders/ORD-1"},
                        "response": {"status": 200, "json_body": {"status": "PENDING"}},
                    }
                ],
            },
        ],
    }


def test_scenario_rest_configuration_and_compilation(tmp_path, monkeypatch) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    monkeypatch.setattr("simuloom.api.routes.service", service)
    simulation = service.create("REST scenarios", contract())

    client = TestClient(app)
    try:
        configured = client.put(
            f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle",
            json=scenario_payload(),
        )
        inspected = client.get(f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle")
        compiled = client.post(
            f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle/compile"
        )
        missing = client.get(f"/api/v1/simulations/{simulation.id}/scenarios/missing")
    finally:
        client.close()

    assert configured.status_code == 200
    assert inspected.json()["definition"]["initial_state"] == "NEW"
    assert compiled.json()["mapping_count"] == 2
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_scenario_mcp_tools_and_resources(tmp_path, monkeypatch) -> None:
    from simuloom.mcp import server as mcp_server

    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    monkeypatch.setattr(mcp_server, "service", service)
    simulation = service.create("MCP scenarios", contract())
    token = _current_principal.set(Principal("tester", Role.OPERATOR, None))
    try:
        configured = mcp_server.configure_scenario(
            simulation.id, "order-lifecycle", scenario_payload()
        )
        compiled = mcp_server.compile_scenario(simulation.id, "order-lifecycle")
        definition = json.loads(mcp_server.scenario_definition(simulation.id, "order-lifecycle"))
    finally:
        _current_principal.reset(token)

    assert configured["definition"]["name"] == "Order lifecycle"
    assert compiled["mapping_count"] == 2
    assert definition["scenario_id"] == "order-lifecycle"


@pytest.mark.asyncio
async def test_scenario_mcp_global_reset_requires_admin() -> None:
    from simuloom.mcp import server as mcp_server

    token = _current_principal.set(Principal("operator", Role.OPERATOR, None))
    try:
        with pytest.raises(PermissionError, match="admin"):
            await mcp_server.reset_all_scenarios()
    finally:
        _current_principal.reset(token)
