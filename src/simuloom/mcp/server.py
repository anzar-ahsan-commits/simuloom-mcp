from __future__ import annotations

import base64
import binascii
import json

from mcp.server.fastmcp import FastMCP

from simuloom.container import service
from simuloom.models import ScenarioDefinition
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
    require_current_role(Role.ADMIN if reset_existing else Role.OPERATOR)
    return (await service.deploy(simulation_id, reset_existing)).model_dump()


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
async def deploy_scenario(simulation_id: str, scenario_id: str) -> dict:
    """Compile, deploy, and initialize one configured scenario."""
    require_current_role(Role.OPERATOR)
    return (await service.deploy_scenario(simulation_id, scenario_id)).model_dump(mode="json")


@mcp.tool()
async def reset_scenario(simulation_id: str, scenario_id: str) -> dict:
    """Reset one deployed scenario to its configured reset state."""
    require_current_role(Role.OPERATOR)
    return (await service.reset_scenario(simulation_id, scenario_id)).model_dump(mode="json")


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
    "scenario://{simulation_id}/{scenario_id}/state",
    mime_type="application/json",
)
async def scenario_state(simulation_id: str, scenario_id: str) -> str:
    """Return the current WireMock state for a configured scenario."""
    require_current_role(Role.VIEWER)
    return (await service.scenario_state(simulation_id, scenario_id)).model_dump_json(indent=2)
