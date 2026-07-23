from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jsonschema import Draft202012Validator

from simuloom.core.compiler import resolve_ref
from simuloom.core.contracts import iter_operations
from simuloom.models import ScenarioDefinition, ScenarioHandler


def wiremock_scenario_name(simulation_id: str, scenario_id: str) -> str:
    return f"SimuLoom:{simulation_id}:{scenario_id}"


def _matching_operation(
    contract: dict[str, Any], handler: ScenarioHandler
) -> tuple[dict[str, Any], str]:
    request_path = urlsplit(handler.request.path).path
    for path, _, method, operation in iter_operations(contract):
        if method != handler.request.method:
            continue
        pattern = "".join(
            "[^/]+" if part.startswith("{") else re.escape(part)
            for part in re.split(r"(\{[^}]+\})", path)
        )
        if re.fullmatch(pattern, request_path):
            return operation, path
    raise ValueError(
        f"Scenario handler '{handler.name}' request does not match an approved "
        f"OpenAPI operation: {handler.request.method} {request_path}"
    )


def _documented_response(operation: dict[str, Any], status: int) -> dict[str, Any]:
    responses = operation.get("responses") or {}
    exact = responses.get(str(status))
    if isinstance(exact, dict):
        return exact
    wildcard = responses.get(f"{status // 100}XX")
    if isinstance(wildcard, dict):
        return wildcard
    default = responses.get("default")
    if isinstance(default, dict):
        return default
    raise ValueError(f"Scenario response status {status} is not documented by the operation")


def _validate_response_body(
    contract: dict[str, Any], handler: ScenarioHandler, response: dict[str, Any]
) -> None:
    if handler.response.json_body is None:
        return
    response = resolve_ref(contract, response)
    media = (response.get("content") or {}).get("application/json")
    if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
        return
    schema = resolve_ref(contract, media["schema"])
    errors = sorted(
        Draft202012Validator(schema).iter_errors(handler.response.json_body),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            f"Scenario handler '{handler.name}' response does not match the approved schema: "
            f"{errors[0].message}"
        )


def validate_scenario_contract(contract: dict[str, Any], definition: ScenarioDefinition) -> None:
    serialized = json.dumps(definition.model_dump(mode="json"), separators=(",", ":"))
    if len(serialized.encode()) > 1_000_000:
        raise ValueError("Scenario definition cannot exceed 1 MiB")
    for state in definition.states:
        triggers: set[tuple[str, str, str]] = set()
        for handler in state.handlers:
            operation, _ = _matching_operation(contract, handler)
            response = _documented_response(operation, handler.response.status)
            _validate_response_body(contract, handler, response)
            trigger = (
                handler.request.method,
                handler.request.path,
                json.dumps(handler.request.json_body, sort_keys=True),
            )
            if trigger in triggers:
                raise ValueError(
                    f"Scenario state '{state.name}' contains ambiguous request handlers"
                )
            triggers.add(trigger)


def compile_scenario_mappings(
    simulation_id: str,
    scenario_id: str,
    definition: ScenarioDefinition,
) -> list[dict[str, Any]]:
    scenario_name = wiremock_scenario_name(simulation_id, scenario_id)
    mappings: list[dict[str, Any]] = []
    for state in definition.states:
        for handler in state.handlers:
            parsed = urlsplit(handler.request.path)
            request: dict[str, Any] = {
                "method": handler.request.method,
                "urlPath": parsed.path,
            }
            query = {
                name: values[-1]
                for name, values in parse_qs(parsed.query, keep_blank_values=True).items()
            }
            query.update(handler.request.query_parameters)
            if query:
                request["queryParameters"] = {
                    name: {"equalTo": value} for name, value in sorted(query.items())
                }
            if handler.request.headers:
                request["headers"] = {
                    name: {"equalTo": value}
                    for name, value in sorted(handler.request.headers.items())
                }
            if handler.request.json_body is not None:
                request["bodyPatterns"] = [
                    {
                        "equalToJson": json.dumps(
                            handler.request.json_body, sort_keys=True, separators=(",", ":")
                        )
                    }
                ]
            response_headers = {"Content-Type": "application/json"}
            response_headers.update(handler.response.headers)
            mapping: dict[str, Any] = {
                "name": f"SimuLoom scenario: {scenario_id} - {handler.name}",
                "priority": 1,
                "scenarioName": scenario_name,
                "requiredScenarioState": state.name,
                "request": request,
                "response": {
                    "status": handler.response.status,
                    "headers": response_headers,
                    "body": json.dumps(handler.response.json_body),
                },
                "metadata": {
                    "simuloomSimulationId": simulation_id,
                    "simuloomScenarioId": scenario_id,
                    "simuloomScenarioState": state.name,
                    "simuloomHandler": handler.name,
                },
            }
            if handler.new_state is not None:
                mapping["newScenarioState"] = handler.new_state
            mappings.append(mapping)
    return mappings
