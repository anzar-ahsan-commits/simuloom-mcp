import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_scenario_api import contract, scenario_payload

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.main import app
from simuloom.models import ScenarioDefinition
from simuloom.security import Principal, Role, _current_principal


@pytest.fixture
def revision_service(tmp_path: Path) -> SimulationService:
    return SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )


def test_rest_revision_history_conflict_and_restore(
    revision_service: SimulationService, monkeypatch
) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", revision_service)
    simulation = revision_service.create("Safe editing", contract())
    path = f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle"
    original = scenario_payload()
    changed = {**original, "description": "Changed by editor one"}

    client = TestClient(app)
    try:
        first = client.put(path, json=original)
        etag_one = first.headers["etag"]
        unchanged = client.put(path, json=original, headers={"If-Match": etag_one})
        second = client.put(path, json=changed, headers={"If-Match": etag_one})
        etag_two = second.headers["etag"]
        conflict = client.put(path, json=original, headers={"If-Match": etag_one})
        history = client.get(f"{path}/history")
        old = client.get(f"{path}/history/1")
        restored = client.post(f"{path}/history/1/restore", headers={"If-Match": etag_two})
        current = client.get(path)
    finally:
        client.close()

    assert first.json()["revision"] == 1
    assert unchanged.json()["revision"] == 1
    assert second.json()["revision"] == 2
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "scenario-edit-conflict"
    assert conflict.json()["detail"]["current_revision"] == 2
    assert [item["revision"] for item in history.json()] == [2, 1]
    assert old.json()["definition"]["description"] == original["description"]
    assert restored.json()["revision"] == 3
    assert current.json()["definition"]["description"] == original["description"]
    assert current.headers["etag"] == restored.headers["etag"]


def test_legacy_scenario_is_adopted_without_rewriting_definition(
    revision_service: SimulationService,
) -> None:
    simulation = revision_service.create("Legacy", contract())
    original = scenario_payload()
    revision_service.repository.write_scenario(simulation.id, "legacy", original)

    view = revision_service.get_scenario(simulation.id, "legacy")
    history = revision_service.scenario_history(simulation.id, "legacy")

    assert view.revision == 1
    assert view.updated_by == "legacy-import"
    assert history[0].created_by == "legacy-import"
    assert revision_service.repository.read_scenario(simulation.id, "legacy") == original


def test_invalid_revision_is_rejected(revision_service: SimulationService) -> None:
    simulation = revision_service.create("Invalid revision", contract())
    revision_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(scenario_payload()),
    )

    with pytest.raises(ValueError, match="positive"):
        revision_service.scenario_revision(simulation.id, "order-lifecycle", 0)
    with pytest.raises(KeyError, match="not found"):
        revision_service.scenario_revision(simulation.id, "order-lifecycle", 99)


def test_rest_rejects_weak_or_malformed_if_match(
    revision_service: SimulationService, monkeypatch
) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", revision_service)
    simulation = revision_service.create("ETag validation", contract())
    path = f"/api/v1/simulations/{simulation.id}/scenarios/order-lifecycle"
    client = TestClient(app)
    try:
        weak = client.put(path, json=scenario_payload(), headers={"If-Match": 'W/"abc"'})
        malformed = client.put(path, json=scenario_payload(), headers={"If-Match": "abc"})
    finally:
        client.close()

    assert weak.status_code == 422
    assert malformed.status_code == 422


def test_out_of_band_definition_change_is_recorded(
    revision_service: SimulationService,
) -> None:
    simulation = revision_service.create("External edit", contract())
    definition = ScenarioDefinition.model_validate(scenario_payload())
    revision_service.configure_scenario(simulation.id, "order-lifecycle", definition)
    external = {**scenario_payload(), "description": "Changed outside the service"}
    revision_service.repository.write_scenario(simulation.id, "order-lifecycle", external)

    view = revision_service.get_scenario(simulation.id, "order-lifecycle")

    assert view.revision == 2
    assert view.updated_by == "external-change"
    assert [
        item.revision
        for item in revision_service.scenario_history(simulation.id, "order-lifecycle")
    ] == [2, 1]


def test_mcp_revision_history_and_restore(revision_service: SimulationService, monkeypatch) -> None:
    from simuloom.mcp import server as mcp_server

    monkeypatch.setattr(mcp_server, "service", revision_service)
    simulation = revision_service.create("MCP safe editing", contract())
    token = _current_principal.set(Principal("mcp-editor", Role.OPERATOR, None))
    try:
        first = mcp_server.configure_scenario(simulation.id, "order-lifecycle", scenario_payload())
        changed = {**scenario_payload(), "description": "MCP update"}
        second = mcp_server.configure_scenario(
            simulation.id,
            "order-lifecycle",
            changed,
            expected_etag=first["etag"],
        )
        history = mcp_server.scenario_history(simulation.id, "order-lifecycle")
        resource = json.loads(
            mcp_server.scenario_revision_history(simulation.id, "order-lifecycle")
        )
        restored = mcp_server.restore_scenario_revision(
            simulation.id,
            "order-lifecycle",
            1,
            expected_etag=second["etag"],
        )
    finally:
        _current_principal.reset(token)

    assert [item["revision"] for item in history] == [2, 1]
    assert resource == history
    assert history[0]["created_by"] == "mcp-editor"
    assert restored["revision"] == 3
    assert restored["definition"]["description"] == scenario_payload()["description"]
