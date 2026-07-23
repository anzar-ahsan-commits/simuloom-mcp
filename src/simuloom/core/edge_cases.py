from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from simuloom.core.cases import build_contract_case, synthetic_value
from simuloom.core.compiler import resolve_ref, response_body, select_response
from simuloom.core.contracts import iter_operations, operation_identifier

MAX_EDGE_CASES = 500


def generate_edge_cases(
    contract: dict[str, Any],
    *,
    include_boundary: bool = True,
    include_negative: bool = True,
    max_per_operation: int = 12,
) -> list[dict[str, Any]]:
    """Generate bounded, deterministic request-schema edge cases from an OpenAPI contract."""
    cases: list[dict[str, Any]] = []
    for path, path_item, method, operation in iter_operations(contract):
        operation_id = operation_identifier(method, path, operation)
        base = build_contract_case(
            contract,
            path,
            path_item,
            method,
            operation,
            case_id=f"EDGE-{operation_id}-base",
            seed=1207,
            variant=0,
        )
        success_status, success_response = select_response(operation)
        error = _error_response(contract, operation)
        candidates: list[dict[str, Any]] = []
        request_schema = _request_schema(contract, operation)
        if request_schema is not None and isinstance(base.get("body"), dict):
            candidates.extend(
                _object_cases(
                    contract,
                    base,
                    request_schema,
                    success_status,
                    response_body(contract, success_response),
                    error,
                    include_boundary,
                    include_negative,
                )
            )
        candidates.extend(
            _parameter_cases(
                contract,
                base,
                path,
                path_item,
                operation,
                success_status,
                response_body(contract, success_response),
                error,
                include_boundary,
                include_negative,
            )
        )
        for index, case in enumerate(candidates[:max_per_operation], start=1):
            case["caseId"] = f"EDGE-{operation_id}-{index:03d}"
            cases.append(case)
            if len(cases) >= MAX_EDGE_CASES:
                return cases
    return cases


def compile_edge_case_mappings(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for case in cases:
        parsed = urlsplit(case["path"])
        request: dict[str, Any] = {"method": case["method"], "urlPath": parsed.path}
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query:
            request["queryParameters"] = {
                name: {"equalTo": value} for name, value in sorted(query.items())
            }
        edge = case["edge"]
        if (
            edge["polarity"] == "negative"
            and edge["constraint"] == "required"
            and edge["location"] == "query"
        ):
            request.setdefault("queryParameters", {})[edge["field"]] = {"absent": True}
        headers = case.get("headers") or {}
        if headers:
            request["headers"] = {
                name: {"equalTo": value} for name, value in sorted(headers.items())
            }
        if (
            edge["polarity"] == "negative"
            and edge["constraint"] == "required"
            and edge["location"] == "header"
        ):
            request.setdefault("headers", {})[edge["field"]] = {"absent": True}
        if case.get("body") is not None:
            request["bodyPatterns"] = [{"equalToJson": json.dumps(case["body"])}]
        mappings.append(
            {
                "name": (
                    f"SimuLoom {edge['polarity']} edge: {case['operationId']} "
                    f"{edge['location']}.{edge['field']} {edge['constraint']}"
                ),
                "priority": 2,
                "request": request,
                "response": {
                    "status": case["expectedStatus"],
                    "headers": {
                        "Content-Type": "application/json",
                        "X-SimuLoom-Data-Source": "contract-edge-cases",
                    },
                    "body": json.dumps(case["responseBody"]),
                },
                "metadata": {
                    "simuloomOperationId": case["operationId"],
                    "simuloomEdgeCase": True,
                    "simuloomEdgePolarity": edge["polarity"],
                    "simuloomConstraint": edge["constraint"],
                    "simuloomField": edge["field"],
                    "synthetic": True,
                },
            }
        )
    return mappings


def _request_schema(contract: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    request_body = resolve_ref(contract, request_body)
    content = request_body.get("content") or {}
    media = content.get("application/json") or next(
        (value for key, value in content.items() if key.endswith("+json")), None
    )
    schema = media.get("schema") if isinstance(media, dict) else None
    return resolve_ref(contract, schema) if isinstance(schema, dict) else None


def _error_response(contract: dict[str, Any], operation: dict[str, Any]) -> tuple[int, Any] | None:
    responses = operation.get("responses") or {}
    for raw_code, response in responses.items():
        code = str(raw_code).upper()
        if code.startswith("4"):
            status = 400 if code == "4XX" else int(code)
            return status, response_body(contract, response or {})
    if "default" in responses:
        return 400, response_body(contract, responses["default"] or {})
    return None


def _object_cases(
    contract: dict[str, Any],
    base: dict[str, Any],
    raw_schema: dict[str, Any],
    success_status: int,
    success_body: Any,
    error: tuple[int, Any] | None,
    include_boundary: bool,
    include_negative: bool,
) -> list[dict[str, Any]]:
    schema = resolve_ref(contract, raw_schema)
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    cases: list[dict[str, Any]] = []
    for name, raw_property in properties.items():
        if not isinstance(raw_property, dict):
            continue
        property_schema = resolve_ref(contract, raw_property)
        if include_negative and error is not None and name in required:
            body = deepcopy(base["body"])
            body.pop(name, None)
            cases.append(
                _case(base, "negative", "required", "body", name, body, error[0], error[1])
            )
        for polarity, constraint, value in _schema_values(
            contract,
            property_schema,
            name,
            include_boundary,
            include_negative and error is not None,
        ):
            body = deepcopy(base["body"])
            body[name] = value
            status, response = (
                (success_status, success_body) if polarity == "boundary" else error  # type: ignore[misc]
            )
            cases.append(_case(base, polarity, constraint, "body", name, body, status, response))
    return cases


def _parameter_cases(
    contract: dict[str, Any],
    base: dict[str, Any],
    path_template: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    success_status: int,
    success_body: Any,
    error: tuple[int, Any] | None,
    include_boundary: bool,
    include_negative: bool,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    parameters: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        if isinstance(raw, dict):
            parameter = resolve_ref(contract, raw)
            parameters[(str(parameter.get("name")), str(parameter.get("in")))] = parameter
    for (name, location), parameter in parameters.items():
        schema = resolve_ref(contract, parameter.get("schema") or {})
        if (
            include_negative
            and error is not None
            and parameter.get("required")
            and location != "path"
        ):
            mutated = _parameter_request(base, location, name, None, remove=True)
            cases.append(
                _case(
                    base,
                    "negative",
                    "required",
                    location,
                    name,
                    mutated.get("body"),
                    error[0],
                    error[1],
                    path=mutated["path"],
                    headers=mutated.get("headers"),
                )
            )
        for polarity, constraint, value in _schema_values(
            contract, schema, name, include_boundary, include_negative and error is not None
        ):
            if constraint == "type" and schema.get("type") == "string":
                continue
            mutated = _parameter_request(base, location, name, value, path_template=path_template)
            status, response = (
                (success_status, success_body) if polarity == "boundary" else error  # type: ignore[misc]
            )
            cases.append(
                _case(
                    base,
                    polarity,
                    constraint,
                    location,
                    name,
                    mutated.get("body"),
                    status,
                    response,
                    path=mutated["path"],
                    headers=mutated.get("headers"),
                )
            )
    return cases


def _schema_values(
    contract: dict[str, Any],
    schema: dict[str, Any],
    field_name: str,
    boundary: bool,
    negative: bool,
) -> list[tuple[str, str, Any]]:
    values: list[tuple[str, str, Any]] = []
    schema_type = schema.get("type")
    if schema_type in {"integer", "number"}:
        step = 1 if schema_type == "integer" else 0.1
        for constraint, direction in (("minimum", -1), ("maximum", 1)):
            if constraint in schema:
                limit = schema[constraint]
                if boundary:
                    values.append(("boundary", constraint, limit))
                if negative:
                    values.append(("negative", constraint, limit + direction * step))
        for constraint, direction in (("exclusiveMinimum", 1), ("exclusiveMaximum", -1)):
            if constraint in schema and not isinstance(schema[constraint], bool):
                limit = schema[constraint]
                if boundary:
                    values.append(("boundary", constraint, limit + direction * step))
                if negative:
                    values.append(("negative", constraint, limit))
    elif schema_type == "string" or any(
        key in schema for key in ("minLength", "maxLength", "enum")
    ):
        if schema.get("enum"):
            enum = schema["enum"]
            if boundary:
                values.extend(
                    ("boundary", "enum", item) for item in dict.fromkeys((enum[0], enum[-1]))
                )
            if negative:
                values.append(("negative", "enum", "SIMULOOM_INVALID_ENUM_VALUE"))
        if "minLength" in schema:
            size = int(schema["minLength"])
            if boundary:
                values.append(("boundary", "minLength", "x" * size))
            if negative and size > 0:
                values.append(("negative", "minLength", "x" * (size - 1)))
        if "maxLength" in schema:
            size = int(schema["maxLength"])
            if boundary:
                values.append(("boundary", "maxLength", "x" * size))
            if negative:
                values.append(("negative", "maxLength", "x" * (size + 1)))
    elif schema_type == "array":
        item_schema = schema.get("items") or {}
        item = synthetic_value(contract, item_schema, field_name=field_name)
        if "minItems" in schema:
            size = int(schema["minItems"])
            if boundary:
                values.append(("boundary", "minItems", [deepcopy(item) for _ in range(size)]))
            if negative and size > 0:
                values.append(("negative", "minItems", [deepcopy(item) for _ in range(size - 1)]))
        if "maxItems" in schema:
            size = int(schema["maxItems"])
            if boundary:
                values.append(("boundary", "maxItems", [deepcopy(item) for _ in range(size)]))
            if negative:
                values.append(("negative", "maxItems", [deepcopy(item) for _ in range(size + 1)]))
    if negative and schema_type in {"string", "integer", "number", "boolean", "array", "object"}:
        wrong = 42 if schema_type in {"string", "boolean", "array", "object"} else "INVALID"
        values.append(("negative", "type", wrong))
    return values


def _parameter_request(
    base: dict[str, Any],
    location: str,
    name: str,
    value: Any,
    *,
    remove: bool = False,
    path_template: str | None = None,
) -> dict[str, Any]:
    mutated = deepcopy(base)
    if location == "query":
        split = urlsplit(mutated["path"])
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        query.pop(name, None) if remove else query.__setitem__(name, _text(value))
        mutated["path"] = urlunsplit(("", "", split.path, urlencode(sorted(query.items())), ""))
    elif location == "header":
        headers = mutated.setdefault("headers", {})
        headers.pop(name, None) if remove else headers.__setitem__(name, _text(value))
    elif location == "path" and not remove and path_template is not None:
        split = urlsplit(mutated["path"])
        template_parts = path_template.strip("/").split("/")
        current_parts = split.path.strip("/").split("/")
        rendered = [
            quote(_text(value), safe="") if part == f"{{{name}}}" else current
            for part, current in zip(template_parts, current_parts, strict=True)
        ]
        mutated["path"] = urlunsplit(("", "", f"/{'/'.join(rendered)}", split.query, ""))
    return mutated


def _case(
    base: dict[str, Any],
    polarity: str,
    constraint: str,
    location: str,
    field: str,
    body: Any,
    status: int,
    response: Any,
    *,
    path: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        **deepcopy(base),
        "path": path or base["path"],
        "headers": deepcopy(headers if headers is not None else base.get("headers", {})),
        "body": deepcopy(body),
        "expectedStatus": status,
        "responseBody": deepcopy(response),
        "edge": {
            "polarity": polarity,
            "constraint": constraint,
            "location": location,
            "field": field,
        },
        "synthetic": True,
    }


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
