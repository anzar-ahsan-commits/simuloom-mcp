from __future__ import annotations

import base64
import binascii
import json

from mcp.server.fastmcp import FastMCP

from simuloom.container import (
    ai_assistant,
    integration_dispatcher,
    platform_store,
    secret_vault,
    service,
)
from simuloom.core.gitops import build_snapshot
from simuloom.models import AIChatMessage, ScenarioDefinition
from simuloom.security import Role, require_current_role

mcp = FastMCP(
    "SimuLoom",
    instructions=(
        "Operate deterministic service simulations from approved OpenAPI contracts. "
        "Never claim generated datasets contain production data."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


def _owned_ai_thread(thread_id: str, subject: str, is_admin: bool = False) -> dict:
    thread = platform_store.get_ai_thread(thread_id)
    if thread["owner"] != subject and not is_admin:
        raise KeyError(f"AI conversation not found: {thread_id}")
    return thread


def _mcp_ai_context(simulation_id: str) -> dict:
    simulation = service.get(simulation_id)
    return {
        "simulation": {
            "id": simulation_id,
            "name": simulation["name"],
            "status": simulation["status"],
            "active_profile": simulation.get("activeProfile", "normal"),
        },
        "approved_operations": [
            item.model_dump(mode="json") for item in service.contract_operations(simulation_id)
        ][:100],
        "scenario_ids": sorted(service.repository.read_scenarios(simulation_id))[:50],
        "safety": {"actions_require_operator_approval": True},
    }


@mcp.tool()
def analyze_contract(contract: dict) -> dict:
    """Validate and summarize an approved OpenAPI 3.x contract without modifying it."""
    require_current_role(Role.VIEWER)
    return service.analyze(contract).model_dump()


@mcp.tool()
def create_simulation(name: str, contract: dict) -> dict:
    """Create a versioned simulation workspace from an approved OpenAPI contract."""
    require_current_role(Role.OPERATOR)
    return service.create(name, contract).model_dump()


@mcp.tool()
def create_ai_conversation(simulation_id: str, title: str = "New conversation") -> dict:
    """Start a persistent, simulation-grounded local-AI conversation."""
    principal = require_current_role(Role.VIEWER)
    service.get(simulation_id)
    return platform_store.create_ai_thread(simulation_id, title, principal.subject)


@mcp.tool()
async def chat_with_simulation(thread_id: str, message: str) -> dict:
    """Ask the local copilot about a simulation; returned actions remain unexecuted proposals."""
    principal = require_current_role(Role.VIEWER)
    if not ai_assistant.enabled:
        raise RuntimeError("Local AI assistance is disabled")
    thread = _owned_ai_thread(thread_id, principal.subject, is_admin=principal.role == Role.ADMIN)
    if not 2 <= len(message) <= 4_000:
        raise ValueError("message must contain between 2 and 4000 characters")
    history = [AIChatMessage.model_validate(item) for item in thread["messages"]]
    platform_store.add_ai_message(thread_id, "user", message)
    completion = await ai_assistant.chat(_mcp_ai_context(thread["simulation_id"]), history, message)
    stored = platform_store.add_ai_message(
        thread_id,
        "assistant",
        completion.answer,
        [
            item.model_dump(mode="json", exclude={"id", "status", "result"})
            for item in completion.actions
        ],
    )
    platform_store.increment_metric("ai_chat_messages_total")
    return stored


@mcp.tool()
async def approve_ai_action(action_id: str) -> dict:
    """Explicitly approve and execute one allowlisted AI proposal as an operator."""
    principal = require_current_role(Role.OPERATOR)
    action = platform_store.get_ai_action(action_id)
    thread = _owned_ai_thread(
        action["thread_id"], principal.subject, is_admin=principal.role == Role.ADMIN
    )
    if action["status"] != "proposed":
        raise ValueError("AI action is no longer awaiting approval")
    claimed = platform_store.claim_ai_action(action_id)
    if claimed is None:
        raise ValueError("AI action is no longer awaiting approval")
    action = claimed
    arguments = action["arguments"]
    simulation_id = thread["simulation_id"]
    try:
        if action["kind"] == "generate_data":
            records = int(arguments.get("records", 25))
            seed = int(arguments.get("seed", 1207))
            if not 1 <= records <= 10_000:
                raise ValueError("AI-proposed record count must be between 1 and 10000")
            result = service.generate_data(simulation_id, records, seed).model_dump(mode="json")
        elif action["kind"] == "compile":
            result = service.compile(simulation_id).model_dump(mode="json")
        elif action["kind"] == "deploy":
            result = (await service.deploy(simulation_id, reset_existing=False)).model_dump(
                mode="json"
            )
        elif action["kind"] == "reset_scenario":
            scenario_id = str(arguments.get("scenario_id", ""))
            service.get_scenario(simulation_id, scenario_id)
            result = (await service.reset_scenario(simulation_id, scenario_id)).model_dump(
                mode="json"
            )
        else:
            raise ValueError("AI action kind is not allowlisted")
    except Exception as exc:
        platform_store.update_ai_action(action_id, "failed", {"error": str(exc)})
        raise
    platform_store.increment_metric("ai_actions_executed_total")
    return platform_store.update_ai_action(action_id, "executed", result)


@mcp.tool()
def generate_test_data(simulation_id: str, records: int = 25, seed: int = 1207) -> dict:
    """Generate reproducible fictional records from the simulation's OpenAPI contract."""
    require_current_role(Role.OPERATOR)
    return service.generate_data(simulation_id, records, seed).model_dump()


@mcp.tool()
def plan_validation(
    simulation_id: str,
    max_dataset_cases: int = 3,
    include_boundary_cases: bool = False,
    include_negative_cases: bool = False,
    max_edge_cases_per_operation: int = 12,
    include_pairwise_cases: bool = False,
    max_pairwise_cases_per_operation: int = 25,
) -> dict:
    """Preview domain-independent validation cases without invoking WireMock."""
    require_current_role(Role.VIEWER)
    return service.plan_validation(
        simulation_id,
        max_dataset_cases,
        include_boundary_cases,
        include_negative_cases,
        max_edge_cases_per_operation,
        include_pairwise_cases,
        max_pairwise_cases_per_operation,
    ).model_dump()


@mcp.tool()
def compile_wiremock_bundle(simulation_id: str) -> dict:
    """Compile a simulation's approved contract into portable WireMock mappings."""
    require_current_role(Role.OPERATOR)
    return service.compile(simulation_id).model_dump()


@mcp.tool()
def activate_profile(
    simulation_id: str,
    profile: str,
    fixed_delay_ms: int = 2_000,
    failure_status: int = 503,
) -> dict:
    """Activate normal, slow, unavailable, or deterministic intermittent behavior."""
    require_current_role(Role.OPERATOR)
    return service.activate_profile(
        simulation_id, profile, fixed_delay_ms, failure_status
    ).model_dump()


@mcp.tool()
async def deploy_simulation(simulation_id: str, reset_existing: bool = False) -> dict:
    """Deploy compiled mappings to the configured WireMock Admin API."""
    principal = require_current_role(Role.ADMIN if reset_existing else Role.OPERATOR)
    return (
        await service.deploy(simulation_id, reset_existing, actor=principal.subject)
    ).model_dump()


@mcp.tool()
async def run_validation(
    simulation_id: str,
    max_dataset_cases: int = 3,
    reset_runtime_state: bool = True,
    include_boundary_cases: bool = False,
    include_negative_cases: bool = False,
    max_edge_cases_per_operation: int = 12,
    include_pairwise_cases: bool = False,
    max_pairwise_cases_per_operation: int = 25,
) -> dict:
    """Execute validation cases and produce contract, coverage, and traffic evidence."""
    require_current_role(Role.OPERATOR)
    report = await service.validate(
        simulation_id,
        max_dataset_cases,
        reset_runtime_state,
        include_boundary_cases,
        include_negative_cases,
        max_edge_cases_per_operation,
        include_pairwise_cases,
        max_pairwise_cases_per_operation,
    )
    return report.model_dump(mode="json")


@mcp.tool()
def export_simulation(simulation_id: str) -> dict:
    """Create a Git-friendly simulation manifest and portable ZIP bundle."""
    require_current_role(Role.VIEWER)
    return service.export_bundle(simulation_id).model_dump()


@mcp.tool()
def import_simulation_bundle(
    bundle_base64: str, source_name: str = "mcp-import.simuloom.zip"
) -> dict:
    """Import a base64-encoded SimuLoom bundle after integrity and safety checks."""
    require_current_role(Role.OPERATOR)
    try:
        data = base64.b64decode(bundle_base64, validate=True)
    except binascii.Error as exc:
        raise ValueError("bundle_base64 is not valid base64") from exc
    return service.import_bundle(data, source_name).model_dump()


@mcp.tool()
def configure_scenario(
    simulation_id: str,
    scenario_id: str,
    definition: dict,
    expected_etag: str | None = None,
) -> dict:
    """Create or replace a validated stateful scenario for a simulation."""
    principal = require_current_role(Role.OPERATOR)
    parsed = ScenarioDefinition.model_validate(definition)
    return service.configure_scenario(
        simulation_id,
        scenario_id,
        parsed,
        actor=principal.subject,
        expected_etag=expected_etag,
    ).model_dump(mode="json")


@mcp.tool()
def scenario_history(simulation_id: str, scenario_id: str) -> list[dict]:
    """List immutable revisions of a configured scenario, newest first."""
    require_current_role(Role.VIEWER)
    return [
        item.model_dump(mode="json")
        for item in service.scenario_history(simulation_id, scenario_id)
    ]


@mcp.tool()
def compare_scenario_revisions(
    simulation_id: str,
    scenario_id: str,
    from_revision: int,
    to_revision: int,
) -> dict:
    """Compare two immutable scenario revisions and flag breaking changes."""
    require_current_role(Role.VIEWER)
    return service.compare_scenario_revisions(
        simulation_id, scenario_id, from_revision, to_revision
    ).model_dump(mode="json")


@mcp.tool()
def get_release_policy(simulation_id: str) -> dict:
    """Read the simulation's opt-in scenario release approval policy."""
    require_current_role(Role.VIEWER)
    return service.scenario_release_policy(simulation_id).model_dump(mode="json")


@mcp.tool()
def update_release_policy(
    simulation_id: str,
    require_approval: bool = False,
    block_breaking_changes: bool = False,
) -> dict:
    """Configure release gates for a simulation; requires admin."""
    principal = require_current_role(Role.ADMIN)
    return service.update_scenario_release_policy(
        simulation_id,
        require_approval,
        block_breaking_changes,
        principal.subject,
    ).model_dump(mode="json")


@mcp.tool()
def request_scenario_review(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    note: str = "",
) -> dict:
    """Request an approval decision for an immutable scenario revision."""
    principal = require_current_role(Role.OPERATOR)
    return service.request_scenario_review(
        simulation_id, scenario_id, revision, principal.subject, note
    ).model_dump(mode="json")


@mcp.tool()
def scenario_reviews(simulation_id: str, scenario_id: str) -> list[dict]:
    """List scenario review requests and immutable decisions, newest first."""
    require_current_role(Role.VIEWER)
    return [
        item.model_dump(mode="json")
        for item in service.scenario_reviews(simulation_id, scenario_id)
    ]


@mcp.tool()
def decide_scenario_review(
    simulation_id: str,
    scenario_id: str,
    review_number: int,
    approved: bool,
    note: str = "",
) -> dict:
    """Approve or reject a pending scenario review; requires admin."""
    principal = require_current_role(Role.ADMIN)
    return service.decide_scenario_review(
        simulation_id,
        scenario_id,
        review_number,
        approved,
        principal.subject,
        note,
    ).model_dump(mode="json")


@mcp.tool()
def restore_scenario_revision(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    expected_etag: str | None = None,
) -> dict:
    """Restore an older definition as a new revision without deleting history."""
    principal = require_current_role(Role.OPERATOR)
    return service.restore_scenario_revision(
        simulation_id,
        scenario_id,
        revision,
        actor=principal.subject,
        expected_etag=expected_etag,
    ).model_dump(mode="json")


@mcp.tool()
def promote_scenario_revision(
    source_simulation_id: str,
    source_scenario_id: str,
    source_revision: int,
    target_simulation_id: str,
    target_scenario_id: str | None = None,
    expected_target_etag: str | None = None,
) -> dict:
    """Promote an immutable revision into another compatible simulation."""
    principal = require_current_role(Role.OPERATOR)
    return service.promote_scenario_revision(
        source_simulation_id,
        source_scenario_id,
        source_revision,
        target_simulation_id,
        target_scenario_id,
        principal.subject,
        expected_target_etag,
    ).model_dump(mode="json")


@mcp.tool()
def create_scenario_template(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    template_id: str,
    name: str,
    description: str = "",
    parameterize: dict[str, str] | None = None,
) -> dict:
    """Save an immutable scenario revision as a reusable workspace template."""
    principal = require_current_role(Role.OPERATOR)
    return service.create_scenario_template(
        simulation_id,
        scenario_id,
        revision,
        template_id,
        name,
        description,
        principal.subject,
        parameterize,
    ).model_dump(mode="json")


@mcp.tool()
def list_scenario_templates() -> list[dict]:
    """List reusable scenario templates."""
    require_current_role(Role.VIEWER)
    return [item.model_dump(mode="json") for item in service.scenario_templates()]


@mcp.tool()
def instantiate_scenario_template(
    template_id: str,
    simulation_id: str,
    scenario_id: str,
    expected_etag: str | None = None,
    parameters: dict[str, str] | None = None,
) -> dict:
    """Instantiate a template into a compatible simulation."""
    principal = require_current_role(Role.OPERATOR)
    return service.instantiate_scenario_template(
        template_id,
        simulation_id,
        scenario_id,
        principal.subject,
        expected_etag,
        parameters,
    ).model_dump(mode="json")


@mcp.resource("template://{template_id}/definition", mime_type="application/json")
def scenario_template_definition(template_id: str) -> str:
    """Return one reusable scenario template."""
    require_current_role(Role.VIEWER)
    return service.get_scenario_template(template_id).model_dump_json(indent=2)


@mcp.tool()
async def inspect_scenario(simulation_id: str, scenario_id: str) -> dict:
    """Inspect a scenario definition and its current WireMock runtime state."""
    require_current_role(Role.VIEWER)
    definition = service.get_scenario(simulation_id, scenario_id)
    runtime = await service.scenario_state(simulation_id, scenario_id)
    return {
        "definition": definition.model_dump(mode="json"),
        "runtime": runtime.model_dump(mode="json"),
    }


@mcp.tool()
def compile_scenario(simulation_id: str, scenario_id: str) -> dict:
    """Compile a configured scenario into deterministic WireMock mappings."""
    require_current_role(Role.OPERATOR)
    return service.compile_scenario(simulation_id, scenario_id).model_dump(mode="json")


@mcp.tool()
async def deploy_scenario(
    simulation_id: str, scenario_id: str, revision: int | None = None
) -> dict:
    """Compile, deploy, and initialize one configured scenario."""
    principal = require_current_role(Role.OPERATOR)
    return (
        await service.deploy_scenario(
            simulation_id, scenario_id, actor=principal.subject, revision=revision
        )
    ).model_dump(mode="json")


@mcp.tool()
def scenario_releases(simulation_id: str, scenario_id: str) -> list[dict]:
    """List immutable scenario deployment records, newest first."""
    require_current_role(Role.VIEWER)
    return [
        item.model_dump(mode="json")
        for item in service.scenario_releases(simulation_id, scenario_id)
    ]


@mcp.tool()
async def rollback_scenario_release(
    simulation_id: str, scenario_id: str, release_number: int
) -> dict:
    """Redeploy a prior release's exact revision and record a new release."""
    principal = require_current_role(Role.OPERATOR)
    return (
        await service.rollback_scenario_release(
            simulation_id, scenario_id, release_number, principal.subject
        )
    ).model_dump(mode="json")


@mcp.tool()
async def reset_scenario(simulation_id: str, scenario_id: str) -> dict:
    """Reset one deployed scenario to its configured reset state."""
    require_current_role(Role.OPERATOR)
    return (await service.reset_scenario(simulation_id, scenario_id)).model_dump(mode="json")


@mcp.tool()
async def advance_scenario_clock(simulation_id: str, scenario_id: str, milliseconds: int) -> dict:
    """Advance deterministic virtual time and apply configured timeout transitions."""
    principal = require_current_role(Role.OPERATOR)
    return (
        await service.advance_scenario_clock(
            simulation_id, scenario_id, milliseconds, principal.subject
        )
    ).model_dump(mode="json")


@mcp.tool()
async def publish_scenario_event(
    simulation_id: str, topic: str, payload: object | None = None
) -> dict:
    """Publish a bounded inbound event and apply matching scenario transitions."""
    principal = require_current_role(Role.OPERATOR)
    return (
        await service.publish_scenario_event(simulation_id, topic, payload, principal.subject)
    ).model_dump(mode="json")


@mcp.tool()
def export_workspace_backup() -> dict:
    """Export a bounded workspace backup as base64; requires admin."""
    require_current_role(Role.ADMIN)
    data = service.workspace_backup()
    return {"bundle_base64": base64.b64encode(data).decode(), "size": len(data)}


@mcp.tool()
def restore_workspace_backup(bundle_base64: str) -> dict:
    """Merge a workspace backup without overwriting existing files; requires admin."""
    principal = require_current_role(Role.ADMIN)
    try:
        data = base64.b64decode(bundle_base64, validate=True)
    except binascii.Error as exc:
        raise ValueError("bundle_base64 is not valid base64") from exc
    return service.restore_workspace(data, principal.subject).model_dump(mode="json")


@mcp.tool()
def export_gitops_snapshot(simulation_id: str) -> dict:
    """Export a deterministic integrity-protected GitOps snapshot."""
    require_current_role(Role.VIEWER)
    return build_snapshot(service.repository, simulation_id)


@mcp.tool()
def create_team_workspace(name: str) -> dict:
    """Create a durable team workspace with the caller as its first admin."""
    principal = require_current_role(Role.ADMIN)
    return platform_store.create_workspace(name, principal.subject)


@mcp.tool()
def list_team_workspaces() -> list[dict]:
    """List team workspaces visible to the caller."""
    principal = require_current_role(Role.VIEWER)
    return platform_store.list_workspaces(
        principal.subject, include_all=principal.role is Role.ADMIN
    )


@mcp.tool()
def set_team_workspace_member(workspace_id: str, subject: str, role: str) -> dict:
    """Create or update a team workspace membership; requires platform admin."""
    require_current_role(Role.ADMIN)
    if role not in {"viewer", "operator", "admin"}:
        raise ValueError("role must be viewer, operator, or admin")
    return platform_store.set_member(workspace_id, subject, role)


@mcp.tool()
def list_workspace_jobs(workspace_id: str) -> list[dict]:
    """List durable background jobs for an accessible team workspace."""
    principal = require_current_role(Role.VIEWER)
    if principal.role is not Role.ADMIN and not platform_store.membership_role(
        workspace_id, principal.subject
    ):
        raise PermissionError("Workspace membership is required")
    return platform_store.list_jobs(workspace_id)


@mcp.tool()
def put_workspace_secret(workspace_id: str, name: str, value: str) -> dict:
    """Encrypt or rotate a workspace secret without returning its value."""
    require_current_role(Role.ADMIN)
    if not secret_vault.available:
        raise RuntimeError("Workspace secret storage is not configured")
    return platform_store.put_secret(workspace_id, name, secret_vault.encrypt(value))


@mcp.tool()
async def dispatch_workspace_integration(
    workspace_id: str, integration_id: str, event_type: str, payload: dict
) -> dict:
    """Deliver one signed, idempotent event through an allowlisted integration."""
    principal = require_current_role(Role.OPERATOR)
    if principal.role is not Role.ADMIN and not platform_store.membership_role(
        workspace_id, principal.subject
    ):
        raise PermissionError("Workspace membership is required")
    integration = platform_store.get_integration(integration_id)
    if integration["workspace_id"] != workspace_id:
        raise KeyError(f"Integration not found: {integration_id}")
    signing_key = None
    if integration["secret_ref"]:
        signing_key = secret_vault.decrypt(
            platform_store.secret_ciphertext(workspace_id, integration["secret_ref"])
        )
    return await integration_dispatcher.dispatch(integration, event_type, payload, signing_key)


@mcp.tool()
async def reset_all_scenarios() -> dict:
    """Reset all WireMock scenarios; this global operation requires admin."""
    require_current_role(Role.ADMIN)
    return (await service.reset_all_scenarios()).model_dump(mode="json")


@mcp.resource("simulation://{simulation_id}/manifest", mime_type="application/json")
def simulation_manifest(simulation_id: str) -> str:
    """Return current simulation metadata as a read-only MCP resource."""
    require_current_role(Role.VIEWER)
    return json.dumps(service.get(simulation_id), indent=2)


@mcp.resource("evidence://{simulation_id}/latest", mime_type="application/json")
def latest_evidence(simulation_id: str) -> str:
    """Return the latest validation evidence report as a read-only MCP resource."""
    require_current_role(Role.VIEWER)
    return service.latest_report(simulation_id).model_dump_json(indent=2)


@mcp.resource("runtime://current/capabilities", mime_type="application/json")
def runtime_capabilities() -> str:
    """Return the selected runtime adapter and its supported capabilities."""
    require_current_role(Role.VIEWER)
    return service.runtime.capabilities().model_dump_json(indent=2)


@mcp.resource("metrics://current/counters", mime_type="application/json")
def current_metrics() -> str:
    """Return bounded low-cardinality SimuLoom operation counters."""
    require_current_role(Role.VIEWER)
    return json.dumps(service.metrics_snapshot(), indent=2)


@mcp.resource("ai-chat://{thread_id}/conversation", mime_type="application/json")
def ai_chat_conversation_resource(thread_id: str) -> str:
    """Read one persistent AI conversation owned by the authenticated principal."""
    principal = require_current_role(Role.VIEWER)
    thread = _owned_ai_thread(thread_id, principal.subject, is_admin=principal.role == Role.ADMIN)
    return json.dumps(thread, indent=2)


@mcp.resource("gitops://simulation/{simulation_id}", mime_type="application/json")
def gitops_snapshot(simulation_id: str) -> str:
    """Return the deterministic GitOps snapshot for a simulation."""
    require_current_role(Role.VIEWER)
    return json.dumps(build_snapshot(service.repository, simulation_id), indent=2)


@mcp.resource("workspace://{workspace_id}/overview", mime_type="application/json")
def team_workspace_overview(workspace_id: str) -> str:
    """Return non-secret team workspace membership and automation metadata."""
    principal = require_current_role(Role.VIEWER)
    if principal.role is not Role.ADMIN and not platform_store.membership_role(
        workspace_id, principal.subject
    ):
        raise PermissionError("Workspace membership is required")
    return json.dumps(
        {
            "workspace": platform_store.get_workspace(workspace_id),
            "members": platform_store.list_members(workspace_id),
            "integrations": platform_store.list_integrations(workspace_id),
            "jobs": platform_store.list_jobs(workspace_id),
            "secrets": platform_store.list_secrets(workspace_id),
        },
        indent=2,
    )


@mcp.resource("audit://domain/events", mime_type="application/json")
def domain_audit_events() -> str:
    """Return recent tamper-evident policy and lifecycle domain events."""
    require_current_role(Role.ADMIN)
    return json.dumps(service.domain_audit_events(), indent=2)


@mcp.resource("audit://domain/verification", mime_type="application/json")
def domain_audit_verification() -> str:
    """Verify the complete domain-event hash chain."""
    require_current_role(Role.ADMIN)
    return json.dumps(service.verify_domain_audit(), indent=2)


@mcp.resource("simulation://{simulation_id}/portable-manifest", mime_type="application/yaml")
def portable_manifest(simulation_id: str) -> str:
    """Return the versioned, Git-friendly simulation.yaml manifest."""
    require_current_role(Role.VIEWER)
    return service.portable_manifest(simulation_id)


@mcp.resource("dataset://{simulation_id}/current", mime_type="application/json")
def current_dataset(simulation_id: str) -> str:
    """Return the current synthetic-only dataset and its generation metadata."""
    require_current_role(Role.VIEWER)
    return service.get_dataset(simulation_id).model_dump_json(indent=2)


@mcp.resource(
    "scenario://{simulation_id}/{scenario_id}/definition",
    mime_type="application/json",
)
def scenario_definition(simulation_id: str, scenario_id: str) -> str:
    """Return a configured scenario definition as a read-only resource."""
    require_current_role(Role.VIEWER)
    return service.get_scenario(simulation_id, scenario_id).model_dump_json(indent=2)


@mcp.resource(
    "scenario://{simulation_id}/{scenario_id}/history",
    mime_type="application/json",
)
def scenario_revision_history(simulation_id: str, scenario_id: str) -> str:
    """Return immutable scenario revision metadata as a read-only resource."""
    require_current_role(Role.VIEWER)
    return json.dumps(
        [
            item.model_dump(mode="json")
            for item in service.scenario_history(simulation_id, scenario_id)
        ],
        indent=2,
    )


@mcp.resource(
    "scenario://{simulation_id}/{scenario_id}/releases",
    mime_type="application/json",
)
def scenario_release_history(simulation_id: str, scenario_id: str) -> str:
    """Return immutable deployment records as a read-only resource."""
    require_current_role(Role.VIEWER)
    return json.dumps(
        [
            item.model_dump(mode="json")
            for item in service.scenario_releases(simulation_id, scenario_id)
        ],
        indent=2,
    )


@mcp.resource(
    "scenario://{simulation_id}/{scenario_id}/reviews",
    mime_type="application/json",
)
def scenario_review_history(simulation_id: str, scenario_id: str) -> str:
    """Return scenario review requests and decisions as a read-only resource."""
    require_current_role(Role.VIEWER)
    return json.dumps(
        [
            item.model_dump(mode="json")
            for item in service.scenario_reviews(simulation_id, scenario_id)
        ],
        indent=2,
    )


@mcp.resource(
    "scenario://{simulation_id}/{scenario_id}/state",
    mime_type="application/json",
)
async def scenario_state(simulation_id: str, scenario_id: str) -> str:
    """Return the current WireMock state for a configured scenario."""
    require_current_role(Role.VIEWER)
    return (await service.scenario_state(simulation_id, scenario_id)).model_dump_json(indent=2)
