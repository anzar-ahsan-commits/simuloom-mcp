from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from simuloom.core.service import SimulationService

READ_TOOLS = frozenset(
    {
        "inspect_scenario",
        "scenario_history",
        "get_release_policy",
        "compare_scenario_revisions",
        "scenario_reviews",
        "list_scenarios",
        "plan_validation",
    }
)

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def build_tool_executor(service: SimulationService, simulation_id: str, actor: str) -> ToolExecutor:
    """Bind a read-only tool dispatcher to one simulation, ignoring any
    simulation_id the model supplies, so a prompt-injected lookup can never
    reach across simulations."""

    def _record(tool: str, arguments: dict[str, Any], outcome: str) -> None:
        path = f"domain/{simulation_id}/ai-read/{tool}"
        service.domain_audit.append(
            request_id=str(uuid.uuid4()),
            subject=actor,
            role="ai",
            key_id=None,
            method="AI_READ",
            path=path,
            status_code=200 if outcome == "recorded" else 422,
            duration_ms=0,
            outcome=outcome,
        )

    async def execute(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in READ_TOOLS:
            _record(tool, arguments, "rejected")
            return {"error": f"tool not permitted: {tool}"}
        try:
            if tool == "inspect_scenario":
                scenario_id = str(arguments.get("scenario_id", ""))
                result = service.get_scenario(simulation_id, scenario_id).model_dump(mode="json")
            elif tool == "scenario_history":
                scenario_id = str(arguments.get("scenario_id", ""))
                result = {
                    "revisions": [
                        item.model_dump(mode="json")
                        for item in service.scenario_history(simulation_id, scenario_id)
                    ]
                }
            elif tool == "get_release_policy":
                result = service.scenario_release_policy(simulation_id).model_dump(mode="json")
            elif tool == "compare_scenario_revisions":
                scenario_id = str(arguments.get("scenario_id", ""))
                from_revision = int(arguments.get("from_revision", 0))
                to_revision = int(arguments.get("to_revision", 0))
                result = service.compare_scenario_revisions(
                    simulation_id, scenario_id, from_revision, to_revision
                ).model_dump(mode="json")
            elif tool == "scenario_reviews":
                scenario_id = str(arguments.get("scenario_id", ""))
                result = {
                    "reviews": [
                        item.model_dump(mode="json")
                        for item in service.scenario_reviews(simulation_id, scenario_id)
                    ]
                }
            elif tool == "list_scenarios":
                result = {
                    "scenarios": [
                        item.model_dump(mode="json")
                        for item in service.list_scenarios(simulation_id)
                    ]
                }
            else:  # plan_validation
                result = service.plan_validation(
                    simulation_id,
                    max_dataset_cases=int(arguments.get("max_dataset_cases", 3)),
                    include_boundary_cases=bool(arguments.get("include_boundary_cases", False)),
                    include_negative_cases=bool(arguments.get("include_negative_cases", False)),
                    max_edge_cases_per_operation=int(
                        arguments.get("max_edge_cases_per_operation", 12)
                    ),
                    include_pairwise_cases=bool(arguments.get("include_pairwise_cases", False)),
                    max_pairwise_cases_per_operation=int(
                        arguments.get("max_pairwise_cases_per_operation", 25)
                    ),
                ).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - surfaced to the model as tool output, not raised
            _record(tool, arguments, "failed")
            return {"error": str(exc)}
        _record(tool, arguments, "recorded")
        return result

    return execute
