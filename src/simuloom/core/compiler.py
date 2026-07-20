from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from simuloom.core.contracts import HTTP_METHODS, iter_operations, operation_identifier


def resolve_ref(contract: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    ref = value.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    current: Any = contract
    try:
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            current = current[int(part)] if isinstance(current, list) else current[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"OpenAPI reference cannot be resolved: {ref}") from exc
    resolved = deepcopy(current)
    if isinstance(resolved, dict):
        resolved.update({key: deepcopy(item) for key, item in value.items() if key != "$ref"})
    return resolved


def sample_from_schema(contract: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> Any:
    if depth > 8:
        return None
    schema = resolve_ref(contract, schema)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("const") is not None:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "oneOf" in schema and schema["oneOf"]:
        return sample_from_schema(contract, schema["oneOf"][0], depth + 1)
    if "anyOf" in schema and schema["anyOf"]:
        return sample_from_schema(contract, schema["anyOf"][0], depth + 1)
    if "allOf" in schema and schema["allOf"]:
        parts = [sample_from_schema(contract, part, depth + 1) for part in schema["allOf"]]
        if all(isinstance(part, dict) for part in parts):
            merged: dict[str, Any] = {}
            for part in parts:
                merged.update(part)
            return merged
        return parts[0]

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if schema_type == "object" or "properties" in schema:
        return {
            name: sample_from_schema(contract, prop, depth + 1)
            for name, prop in (schema.get("properties") or {}).items()
        }
    if schema_type == "array":
        return [sample_from_schema(contract, schema.get("items") or {}, depth + 1)]
    if schema_type == "integer":
        return schema.get("minimum", 1)
    if schema_type == "number":
        return schema.get("minimum", 1.0)
    if schema_type == "boolean":
        return True
    if schema_type == "null":
        return None
    if schema.get("format") == "date":
        return "2026-01-15"
    if schema.get("format") == "date-time":
        return "2026-01-15T12:00:00Z"
    if schema.get("format") == "uuid":
        return "00000000-0000-4000-8000-000000000001"
    value = "string"
    minimum_length = int(schema.get("minLength", 0))
    if len(value) < minimum_length:
        value += "x" * (minimum_length - len(value))
    maximum_length = schema.get("maxLength")
    return value[: int(maximum_length)] if maximum_length is not None else value


def select_response(operation: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    responses = operation.get("responses") or {}
    for code, response in responses.items():
        normalized = str(code).upper()
        if normalized.startswith("2"):
            return (200 if normalized == "2XX" else int(normalized)), response or {}
    if "default" in responses:
        return 200, responses["default"] or {}
    return 200, {}


def response_body(contract: dict[str, Any], response: dict[str, Any]) -> Any:
    response = resolve_ref(contract, response)
    content = response.get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), {})
    if "example" in media:
        return media["example"]
    examples = media.get("examples") or {}
    if examples:
        first = next(iter(examples.values()))
        return first.get("value", first)
    schema = media.get("schema")
    return sample_from_schema(contract, schema) if isinstance(schema, dict) else {}


def compile_wiremock_mappings(contract: dict[str, Any]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for path, _, method, operation in iter_operations(contract):
        status, response = select_response(operation)
        request: dict[str, Any] = {"method": method}
        if "{" in path:
            pattern = "".join(
                "[^/]+" if part.startswith("{") else re.escape(part)
                for part in re.split(r"(\{[^}]+\})", path)
            )
            request["urlPathPattern"] = f"^{pattern}$"
        else:
            request["urlPath"] = path
        operation_id = operation_identifier(method, path, operation)
        mappings.append(
            {
                "name": f"SimuLoom: {operation_id}",
                "priority": 10,
                "request": request,
                "response": {
                    "status": status,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(response_body(contract, response)),
                },
                "metadata": {"simuloomOperationId": operation_id},
            }
        )
    return mappings


def compile_eligibility_dataset_mappings(
    contract: dict[str, Any], members: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], set[str]]:
    """Compile correlated member records when the contract declares a member-id lookup."""
    mappings: list[dict[str, Any]] = []
    overridden_operations: set[str] = set()
    for path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict) or "{memberId}" not in path:
            continue
        operation = path_item.get("get")
        if not isinstance(operation, dict):
            continue
        operation_id = str(operation.get("operationId", "get-member-eligibility"))
        overridden_operations.add(operation_id)
        for member in members:
            member_id = str(member["memberId"])
            response_body = {
                "memberId": member_id,
                "status": member["status"],
                "planName": member["plan"]["planName"],
                "effectiveDate": member["effectiveDate"],
                "synthetic": True,
            }
            mappings.append(
                {
                    "name": f"SimuLoom dataset: {operation_id} - {member_id}",
                    "priority": 1,
                    "request": {"method": "GET", "urlPath": path.replace("{memberId}", member_id)},
                    "response": {
                        "status": 200,
                        "headers": {
                            "Content-Type": "application/json",
                            "X-SimuLoom-Data-Source": "members",
                        },
                        "body": json.dumps(response_body),
                    },
                    "metadata": {
                        "simuloomOperationId": operation_id,
                        "simuloomDataset": "members",
                        "simuloomRecordId": member_id,
                        "synthetic": True,
                    },
                }
            )

        pattern = re.sub(r"\{memberId\}", "[^/]+", path)
        mappings.append(
            {
                "name": f"SimuLoom dataset fallback: {operation_id}",
                "priority": 100,
                "request": {"method": "GET", "urlPathPattern": f"^{pattern}$"},
                "response": {
                    "status": 404,
                    "headers": {
                        "Content-Type": "application/json",
                        "X-SimuLoom-Data-Source": "members",
                    },
                    "body": json.dumps(
                        {
                            "code": "MEMBER_NOT_FOUND",
                            "message": "No synthetic member matched the supplied memberId",
                            "synthetic": True,
                        }
                    ),
                },
                "metadata": {
                    "simuloomOperationId": operation_id,
                    "simuloomDataset": "members",
                    "simuloomFallback": True,
                },
            }
        )
    return mappings, overridden_operations


def compile_eligibility_journey(
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Compile the approved async eligibility operations into a WireMock state machine."""
    begin: tuple[str, str] | None = None
    status: tuple[str, str] | None = None
    for path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId", ""))
            if operation_id == "beginEligibilityRequest":
                begin = (path, operation_id)
            elif operation_id == "getEligibilityRequest":
                status = (path, operation_id)

    if begin is None or status is None:
        return [], set()

    begin_path, begin_operation = begin
    status_path, status_operation = status
    request_id = "REQ-SYN-001"
    status_url = status_path.replace("{requestId}", request_id)
    scenario = "SimuLoom eligibility request journey"

    def response_body(state: str) -> str:
        return json.dumps({"requestId": request_id, "status": state, "synthetic": True})

    mappings = [
        {
            "name": "SimuLoom journey: submit eligibility request",
            "priority": 1,
            "scenarioName": scenario,
            "newScenarioState": "PROCESSING",
            "request": {"method": "POST", "urlPath": begin_path},
            "response": {
                "status": 202,
                "headers": {"Content-Type": "application/json"},
                "body": response_body("SUBMITTED"),
            },
            "metadata": {
                "simuloomOperationId": begin_operation,
                "simuloomJourney": "eligibility-request",
                "simuloomStep": "SUBMITTED",
            },
        },
        {
            "name": "SimuLoom journey: eligibility request processing",
            "priority": 1,
            "scenarioName": scenario,
            "requiredScenarioState": "PROCESSING",
            "newScenarioState": "COMPLETED",
            "request": {"method": "GET", "urlPath": status_url},
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "body": response_body("PROCESSING"),
            },
            "metadata": {
                "simuloomOperationId": status_operation,
                "simuloomJourney": "eligibility-request",
                "simuloomStep": "PROCESSING",
            },
        },
        {
            "name": "SimuLoom journey: eligibility request completed",
            "priority": 1,
            "scenarioName": scenario,
            "requiredScenarioState": "COMPLETED",
            "request": {"method": "GET", "urlPath": status_url},
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "body": response_body("COMPLETED"),
            },
            "metadata": {
                "simuloomOperationId": status_operation,
                "simuloomJourney": "eligibility-request",
                "simuloomStep": "COMPLETED",
            },
        },
    ]
    return mappings, {begin_operation, status_operation}
