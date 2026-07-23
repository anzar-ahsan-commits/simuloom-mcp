from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_scenarios import ScenarioWireMock, contract, definition_payload

from simuloom.core.repository import WorkspaceRepository
from simuloom.core.scenario_approvals import ScenarioApprovalError
from simuloom.core.service import SimulationService
from simuloom.main import app
from simuloom.models import ScenarioDefinition
from simuloom.security import Principal, Role, _current_principal


@pytest.fixture
def approval_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_approval_policy_is_opt_in_and_pins_revision(
    approval_service: SimulationService,
) -> None:
    simulation = approval_service.create("Approval gates", contract())
    first = approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    ungoverned = await approval_service.deploy_scenario(simulation.id, "order-lifecycle")
    policy = approval_service.update_scenario_release_policy(simulation.id, True, False, "admin")

    with pytest.raises(ScenarioApprovalError, match="requires approval"):
        await approval_service.deploy_scenario(simulation.id, "order-lifecycle")

    review = approval_service.request_scenario_review(
        simulation.id, "order-lifecycle", 1, "operator", "Ready"
    )
    approved = approval_service.decide_scenario_review(
        simulation.id, "order-lifecycle", review.review_number, True, "admin", "Approved"
    )
    governed = await approval_service.deploy_scenario(simulation.id, "order-lifecycle")

    assert ungoverned.release_number == 1
    assert policy.require_approval is True
    assert approved.status == "approved"
    assert approved.etag == first.etag
    assert governed.release_number == 2


@pytest.mark.asyncio
async def test_rejection_rereview_and_already_decided_validation(
    approval_service: SimulationService,
) -> None:
    simulation = approval_service.create("Review decisions", contract())
    approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    approval_service.update_scenario_release_policy(simulation.id, True, False, "admin")
    approval_service.request_scenario_review(simulation.id, "order-lifecycle", 1, "operator")
    rejected = approval_service.decide_scenario_review(
        simulation.id, "order-lifecycle", 1, False, "admin", "Needs changes"
    )

    with pytest.raises(ValueError, match="already been decided"):
        approval_service.decide_scenario_review(simulation.id, "order-lifecycle", 1, True, "admin")
    second = approval_service.request_scenario_review(
        simulation.id, "order-lifecycle", 1, "operator", "Please reconsider"
    )

    assert rejected.status == "rejected"
    assert second.review_number == 2
    assert [
        item.review_number
        for item in approval_service.scenario_reviews(simulation.id, "order-lifecycle")
    ] == [2, 1]


@pytest.mark.asyncio
async def test_breaking_change_policy_and_rollback_exception(
    approval_service: SimulationService,
) -> None:
    simulation = approval_service.create("Breaking policy", contract())
    first = approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    release = await approval_service.deploy_scenario(simulation.id, "order-lifecycle")
    changed = definition_payload()
    changed["states"][0]["handlers"][0]["new_state"] = None
    approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(changed),
        expected_etag=first.etag,
    )
    approval_service.update_scenario_release_policy(simulation.id, False, True, "admin")

    with pytest.raises(ScenarioApprovalError, match="blocked breaking changes"):
        await approval_service.deploy_scenario(simulation.id, "order-lifecycle")

    rollback = await approval_service.rollback_scenario_release(
        simulation.id, "order-lifecycle", release.release_number or 1, "operator"
    )
    assert rollback.revision == 1


def test_approval_rest_workflow(approval_service: SimulationService, monkeypatch) -> None:
    monkeypatch.setattr("simuloom.api.routes.service", approval_service)
    simulation = approval_service.create("REST approvals", contract())
    approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    root = f"/api/v1/simulations/{simulation.id}"
    scenario = f"{root}/scenarios/order-lifecycle"
    client = TestClient(app)
    try:
        policy = client.put(
            f"{root}/release-policy",
            json={"require_approval": True, "block_breaking_changes": False},
        )
        blocked = client.post(f"{scenario}/deploy")
        requested = client.post(f"{scenario}/history/1/review", json={"note": "Ready"})
        approved = client.post(f"{scenario}/reviews/1/approve", json={"note": "Ship it"})
        deployed = client.post(f"{scenario}/deploy")
        reviews = client.get(f"{scenario}/reviews")
    finally:
        client.close()

    assert policy.status_code == 200
    assert blocked.status_code == 409
    assert requested.json()["status"] == "pending"
    assert approved.json()["status"] == "approved"
    assert deployed.status_code == 200
    assert reviews.json()[0]["decision_note"] == "Ship it"


def test_approval_mcp_workflow(approval_service: SimulationService, monkeypatch) -> None:
    from simuloom.mcp import server as mcp_server

    monkeypatch.setattr(mcp_server, "service", approval_service)
    simulation = approval_service.create("MCP approvals", contract())
    approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    token = _current_principal.set(Principal("admin-reviewer", Role.ADMIN, None))
    try:
        policy = mcp_server.update_release_policy(simulation.id, True, False)
        requested = mcp_server.request_scenario_review(
            simulation.id, "order-lifecycle", 1, "Review me"
        )
        decided = mcp_server.decide_scenario_review(
            simulation.id, "order-lifecycle", 1, True, "Approved"
        )
        reviews = mcp_server.scenario_reviews(simulation.id, "order-lifecycle")
        resource = mcp_server.scenario_review_history(simulation.id, "order-lifecycle")
    finally:
        _current_principal.reset(token)

    assert policy["require_approval"] is True
    assert requested["requested_by"] == "admin-reviewer"
    assert decided["status"] == "approved"
    assert "admin-reviewer" in resource
    assert reviews[0]["review_number"] == 1


def test_policy_domain_audit_is_hash_chained(
    approval_service: SimulationService,
) -> None:
    simulation = approval_service.create("Policy evidence", contract())
    approval_service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    approval_service.update_scenario_release_policy(simulation.id, True, False, "admin")
    approval_service.request_scenario_review(simulation.id, "order-lifecycle", 1, "operator")
    approval_service.decide_scenario_review(simulation.id, "order-lifecycle", 1, True, "admin")

    events = approval_service.domain_audit_events()
    verification = approval_service.verify_domain_audit()

    assert [event["path"].split("/")[-1] for event in events] == [
        "policy-update",
        "review-request",
        "review-approved",
    ]
    assert verification["valid"] is True
    assert verification["total_events"] == 3
