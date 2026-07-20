from __future__ import annotations

import json
import random
import re
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from simuloom.core.compiler import resolve_ref, response_body, select_response
from simuloom.core.contracts import iter_operations, operation_identifier


def synthetic_value(
    contract: dict[str, Any],
    schema: dict[str, Any],
    *,
    field_name: str = "value",
    seed: int = 1207,
    variant: int = 0,
    depth: int = 0,
) -> Any:
    """Create a deterministic fictional value while honoring common JSON Schema constraints."""
    if depth > 8:
        return None
    schema = resolve_ref(contract, schema)
    if "example" in schema:
        return deepcopy(schema["example"])
    if "default" in schema:
        return deepcopy(schema["default"])
    if schema.get("const") is not None:
        return deepcopy(schema["const"])
    if schema.get("enum"):
        values = schema["enum"]
        return deepcopy(values[variant % len(values)])
    if schema.get("allOf"):
        parts = [
            synthetic_value(
                contract,
                part,
                field_name=field_name,
                seed=seed,
                variant=variant,
                depth=depth + 1,
            )
            for part in schema["allOf"]
        ]
        if all(isinstance(part, dict) for part in parts):
            merged: dict[str, Any] = {}
            for part in parts:
                merged.update(part)
            return merged
        return parts[0] if parts else None
    for union in ("oneOf", "anyOf"):
        if schema.get(union):
            choices = schema[union]
            return synthetic_value(
                contract,
                choices[variant % len(choices)],
                field_name=field_name,
                seed=seed,
                variant=variant,
                depth=depth + 1,
            )

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if schema_type == "object" or "properties" in schema:
        return {
            name: synthetic_value(
                contract,
                property_schema,
                field_name=name,
                seed=seed,
                variant=variant,
                depth=depth + 1,
            )
            for name, property_schema in (schema.get("properties") or {}).items()
            if isinstance(property_schema, dict)
        }
    if schema_type == "array":
        minimum = max(0, int(schema.get("minItems", 1)))
        maximum = max(minimum, int(schema.get("maxItems", max(1, minimum))))
        count = max(minimum, min(maximum, 3))
        item_schema = schema.get("items") or {}
        return [
            synthetic_value(
                contract,
                item_schema,
                field_name=field_name,
                seed=seed,
                variant=variant + index,
                depth=depth + 1,
            )
            for index in range(count)
        ]
    if schema_type == "integer":
        minimum = int(schema.get("minimum", 1))
        maximum = int(schema.get("maximum", minimum + 10_000))
        return min(maximum, minimum + variant)
    if schema_type == "number":
        minimum = float(schema.get("minimum", 1.0))
        maximum = float(schema.get("maximum", minimum + 10_000.0))
        return min(maximum, minimum + variant / 10)
    if schema_type == "boolean":
        return variant % 2 == 0
    if schema_type == "null":
        return None

    normalized_name = re.sub(r"[^a-z0-9]+", "-", field_name.lower()).strip("-")
    suffix = f"{seed}-{variant + 1}"
    value_format = schema.get("format")
    if value_format == "date":
        return (date(2026, 1, 1) + timedelta(days=variant)).isoformat()
    if value_format == "date-time":
        moment = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=variant)
        return moment.isoformat().replace("+00:00", "Z")
    if value_format == "uuid":
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"simuloom:{field_name}:{suffix}"))
    if value_format == "email":
        return f"synthetic-{suffix}@example.test"
    if value_format in {"uri", "url"}:
        return f"https://example.test/synthetic/{suffix}"

    rng = random.Random(f"{seed}:{field_name}:{variant}")
    token = rng.randrange(100_000, 999_999)
    if normalized_name.endswith("id") or normalized_name == "id":
        value = f"syn-{normalized_name}-{suffix}"
    else:
        value = f"synthetic-{normalized_name or 'value'}-{token}"
    minimum_length = int(schema.get("minLength", 0))
    if len(value) < minimum_length:
        value += "x" * (minimum_length - len(value))
    maximum_length = schema.get("maxLength")
    return value[: int(maximum_length)] if maximum_length is not None else value


def generate_contract_cases(
    contract: dict[str, Any], records: int, seed: int
) -> list[dict[str, Any]]:
    operations = list(iter_operations(contract))
    if not operations:
        raise ValueError("The OpenAPI document contains no HTTP operations")
    cases: list[dict[str, Any]] = []
    for index in range(records):
        path, path_item, method, operation = operations[index % len(operations)]
        variant = index // len(operations)
        cases.append(
            build_contract_case(
                contract,
                path,
                path_item,
                method,
                operation,
                case_id=f"SYN-{seed:04d}-{index + 1:06d}",
                seed=seed,
                variant=variant,
            )
        )
    return cases


def baseline_contract_cases(contract: dict[str, Any], seed: int = 1207) -> list[dict[str, Any]]:
    return generate_contract_cases(contract, len(list(iter_operations(contract))), seed)


def build_contract_case(
    contract: dict[str, Any],
    path: str,
    path_item: dict[str, Any],
    method: str,
    operation: dict[str, Any],
    *,
    case_id: str,
    seed: int,
    variant: int,
) -> dict[str, Any]:
    operation_id = operation_identifier(method, path, operation)
    parameters_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_parameter in [
        *(path_item.get("parameters") or []),
        *(operation.get("parameters") or []),
    ]:
        if isinstance(raw_parameter, dict):
            parameter = resolve_ref(contract, raw_parameter)
            identity = (str(parameter.get("name", "parameter")), str(parameter.get("in", "")))
            parameters_by_identity[identity] = parameter
    resolved_path = path
    query: list[tuple[str, str]] = []
    headers: dict[str, str] = {}
    cookies: list[str] = []
    declared_path_parameters: set[str] = set()
    for parameter in parameters_by_identity.values():
        name = str(parameter.get("name", "parameter"))
        location = parameter.get("in")
        schema = parameter.get("schema") or {}
        value = parameter.get("example")
        if value is None:
            value = synthetic_value(
                contract,
                schema,
                field_name=name,
                seed=seed,
                variant=variant,
            )
        rendered = _parameter_text(value)
        if location == "path":
            declared_path_parameters.add(name)
            resolved_path = resolved_path.replace(f"{{{name}}}", quote(rendered, safe=""))
        elif location == "query":
            query.append((name, rendered))
        elif location == "header":
            headers[name] = rendered
        elif location == "cookie":
            cookies.append(f"{name}={rendered}")
    for name in re.findall(r"\{([^}]+)\}", resolved_path):
        if name not in declared_path_parameters:
            fallback = synthetic_value(
                contract,
                {"type": "string"},
                field_name=name,
                seed=seed,
                variant=variant,
            )
            resolved_path = resolved_path.replace(f"{{{name}}}", quote(str(fallback), safe=""))
    if query:
        resolved_path = f"{resolved_path}?{urlencode(query)}"
    if cookies:
        headers["Cookie"] = "; ".join(cookies)

    body: Any = None
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        request_body = resolve_ref(contract, request_body)
        media = _json_media(request_body.get("content") or {})
        if media is not None:
            if "example" in media:
                body = deepcopy(media["example"])
            elif isinstance(media.get("schema"), dict):
                body = synthetic_value(
                    contract,
                    media["schema"],
                    field_name=f"{operation_id}-request",
                    seed=seed,
                    variant=variant,
                )

    status, response = select_response(operation)
    return {
        "caseId": case_id,
        "operationId": operation_id,
        "method": method,
        "path": resolved_path,
        "headers": headers,
        "body": body,
        "expectedStatus": status,
        "responseBody": response_body(contract, response),
        "synthetic": True,
    }


def compile_contract_case_mappings(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for case in cases:
        parsed = urlsplit(case["path"])
        request: dict[str, Any] = {"method": case["method"], "urlPath": parsed.path}
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query:
            request["queryParameters"] = {
                name: {"equalTo": values[0]} for name, values in sorted(query.items())
            }
        if case.get("headers"):
            request["headers"] = {
                name: {"equalTo": value} for name, value in case["headers"].items()
            }
        if case.get("body") is not None:
            request["bodyPatterns"] = [{"equalToJson": json.dumps(case["body"])}]
        mappings.append(
            {
                "name": f"SimuLoom synthetic case: {case['caseId']}",
                "priority": 1,
                "request": request,
                "response": {
                    "status": case["expectedStatus"],
                    "headers": {
                        "Content-Type": "application/json",
                        "X-SimuLoom-Data-Source": "contract-cases",
                    },
                    "body": json.dumps(case["responseBody"]),
                },
                "metadata": {
                    "simuloomOperationId": case["operationId"],
                    "simuloomDataset": "contract-cases",
                    "simuloomRecordId": case["caseId"],
                    "synthetic": True,
                },
            }
        )
    return mappings


def validate_contract_cases(contract: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    operations = {
        operation_identifier(method, path, operation): (method, path)
        for path, _, method, operation in iter_operations(contract)
    }
    case_ids: set[str] = set()
    for case in cases:
        case_id = case.get("caseId")
        operation_id = case.get("operationId")
        if not isinstance(case_id, str) or not case_id.startswith("SYN-"):
            raise ValueError("Every contract case requires a synthetic caseId")
        if case_id in case_ids:
            raise ValueError("Contract case IDs must be unique")
        case_ids.add(case_id)
        if operation_id not in operations:
            raise ValueError(f"Contract case references unknown operation {operation_id}")
        expected_method, path_template = operations[operation_id]
        if case.get("method") != expected_method:
            raise ValueError(f"Contract case method does not match operation {operation_id}")
        path = case.get("path")
        if not isinstance(path, str) or not path.startswith("/") or "://" in path:
            raise ValueError("Contract case paths must be relative API paths")
        parsed_path = urlsplit(path).path
        decoded_path = unquote(parsed_path)
        if ".." in PurePosixPath(decoded_path).parts:
            raise ValueError("Contract case paths cannot contain traversal segments")
        template_pattern = "".join(
            "[^/]+" if part.startswith("{") else re.escape(part)
            for part in re.split(r"(\{[^}]+\})", path_template)
        )
        if re.fullmatch(template_pattern, decoded_path) is None:
            raise ValueError(f"Contract case path does not match operation {operation_id}")
        status = case.get("expectedStatus")
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("Contract case expectedStatus must be an HTTP status code")
        headers = case.get("headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in headers.items()
        ):
            raise ValueError("Contract case headers must contain string names and values")
        restricted_headers = {"host", "content-length", "transfer-encoding", "connection"}
        if restricted_headers & {name.lower() for name in headers}:
            raise ValueError("Contract cases cannot override transport-controlled headers")
        if "responseBody" not in case:
            raise ValueError("Every contract case requires a responseBody")


def _json_media(content: dict[str, Any]) -> dict[str, Any] | None:
    media = content.get("application/json")
    if isinstance(media, dict):
        return media
    for media_type, definition in content.items():
        if media_type.endswith("+json") and isinstance(definition, dict):
            return definition
    return None


def _parameter_text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)
