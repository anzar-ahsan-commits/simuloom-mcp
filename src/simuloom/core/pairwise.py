from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker

from simuloom.core.cases import build_contract_case, synthetic_value
from simuloom.core.compiler import resolve_ref, response_body, select_response
from simuloom.core.contracts import iter_operations, operation_identifier

MAX_FACTORS = 12
MAX_VALUES_PER_FACTOR = 4
MAX_PAIRWISE_CASES = 500
ABSENT = object()


@dataclass(frozen=True, slots=True)
class FactorValue:
    label: str
    value: Any


@dataclass(frozen=True, slots=True)
class PairwiseFactor:
    identity: str
    location: str
    field: str
    values: tuple[FactorValue, ...]


def generate_pairwise_cases(
    contract: dict[str, Any], *, max_per_operation: int = 25
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path, path_item, method, operation in iter_operations(contract):
        operation_id = operation_identifier(method, path, operation)
        base = build_contract_case(
            contract,
            path,
            path_item,
            method,
            operation,
            case_id=f"PAIR-{operation_id}-base",
            seed=1207,
            variant=0,
        )
        factors = extract_pairwise_factors(contract, path_item, operation)
        if len(factors) < 2:
            continue
        factors = factors[:MAX_FACTORS]
        rows, total_pairs = _covering_rows(factors, max_per_operation)
        success_status, response = select_response(operation)
        for index, row in enumerate(rows, start=1):
            request = _apply_row(base, path, factors, row)
            pair_ids = sorted(f"{operation_id}:{pair}" for pair in _row_pair_ids(factors, row))
            cases.append(
                {
                    **request,
                    "caseId": f"PAIR-{operation_id}-{index:03d}",
                    "operationId": operation_id,
                    "method": method,
                    "expectedStatus": success_status,
                    "responseBody": response_body(contract, response),
                    "pairwise": {
                        "assignments": {
                            factor.identity: factor.values[value_index].label
                            for factor, value_index in zip(factors, row, strict=True)
                        },
                        "pairIds": pair_ids,
                        "totalPairs": total_pairs,
                    },
                    "synthetic": True,
                }
            )
            if len(cases) >= MAX_PAIRWISE_CASES:
                return cases
    return cases


def extract_pairwise_factors(
    contract: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> list[PairwiseFactor]:
    factors: list[PairwiseFactor] = []
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        request_body = resolve_ref(contract, request_body)
        content = request_body.get("content") or {}
        media = content.get("application/json") or next(
            (value for key, value in content.items() if key.endswith("+json")), None
        )
        schema = media.get("schema") if isinstance(media, dict) else None
        if isinstance(schema, dict):
            schema = resolve_ref(contract, schema)
            union = schema.get("oneOf") or schema.get("anyOf")
            if isinstance(union, list) and len(union) >= 2:
                values = tuple(
                    FactorValue(
                        f"variant-{index + 1}",
                        synthetic_value(contract, branch, field_name="request-body", variant=index),
                    )
                    for index, branch in enumerate(union[:MAX_VALUES_PER_FACTOR])
                    if isinstance(branch, dict)
                )
                if len(values) >= 2:
                    factors.append(PairwiseFactor("body.$variant", "body", "$variant", values))
            else:
                required = set(schema.get("required") or [])
                for name, property_schema in (schema.get("properties") or {}).items():
                    if isinstance(property_schema, dict):
                        factor = _factor(
                            contract,
                            "body",
                            name,
                            property_schema,
                            optional=name not in required,
                        )
                        if factor is not None:
                            factors.append(factor)

    parameters: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        if isinstance(raw, dict):
            parameter = resolve_ref(contract, raw)
            parameters[(str(parameter.get("name")), str(parameter.get("in")))] = parameter
    for (name, location), parameter in parameters.items():
        factor = _factor(
            contract,
            location,
            name,
            parameter.get("schema") or {},
            optional=not bool(parameter.get("required")),
        )
        if factor is not None:
            factors.append(factor)
    return factors[:MAX_FACTORS]


def compile_pairwise_mappings(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for case in cases:
        parsed = urlsplit(case["path"])
        request: dict[str, Any] = {"method": case["method"], "urlPath": parsed.path}
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query:
            request["queryParameters"] = {
                name: {"equalTo": value} for name, value in sorted(query.items())
            }
        for identity, label in case["pairwise"]["assignments"].items():
            location, field = identity.split(".", 1)
            if label == "absent" and location == "query":
                request.setdefault("queryParameters", {})[field] = {"absent": True}
        if case.get("headers"):
            request["headers"] = {
                name: {"equalTo": value} for name, value in sorted(case["headers"].items())
            }
        for identity, label in case["pairwise"]["assignments"].items():
            location, field = identity.split(".", 1)
            if label == "absent" and location == "header":
                request.setdefault("headers", {})[field] = {"absent": True}
        if case.get("body") is not None:
            request["bodyPatterns"] = [{"equalToJson": json.dumps(case["body"])}]
        mappings.append(
            {
                "name": f"SimuLoom pairwise: {case['operationId']} {case['caseId']}",
                "priority": 3,
                "request": request,
                "response": {
                    "status": case["expectedStatus"],
                    "headers": {
                        "Content-Type": "application/json",
                        "X-SimuLoom-Data-Source": "contract-pairwise",
                    },
                    "body": json.dumps(case["responseBody"]),
                },
                "metadata": {
                    "simuloomOperationId": case["operationId"],
                    "simuloomPairwiseCase": True,
                    "simuloomRecordId": case["caseId"],
                    "synthetic": True,
                },
            }
        )
    return mappings


def _factor(
    contract: dict[str, Any],
    location: str,
    field: str,
    raw_schema: dict[str, Any],
    *,
    optional: bool,
) -> PairwiseFactor | None:
    schema = _resolve_schema(contract, raw_schema)
    values = _representative_values(contract, schema, field)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    values = [value for value in values if not list(validator.iter_errors(value.value))]
    if location != "body":
        values = [value for value in values if value.value is not None]
    if optional and location != "path":
        values.append(FactorValue("absent", ABSENT))
    unique: list[FactorValue] = []
    seen: set[str] = set()
    for value in values:
        fingerprint = _fingerprint(value.value)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(value)
    if len(unique) < 2:
        return None
    return PairwiseFactor(
        identity=f"{location}.{field}",
        location=location,
        field=field,
        values=tuple(unique[:MAX_VALUES_PER_FACTOR]),
    )


def _representative_values(
    contract: dict[str, Any], schema: dict[str, Any], field: str
) -> list[FactorValue]:
    if "const" in schema:
        return [FactorValue("const", deepcopy(schema["const"]))]
    if "pattern" in schema and not schema.get("enum"):
        return []
    union = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(union, list):
        values = [
            FactorValue(
                f"variant-{index + 1}",
                synthetic_value(contract, branch, field_name=field, variant=index),
            )
            for index, branch in enumerate(union[:MAX_VALUES_PER_FACTOR])
            if isinstance(branch, dict)
        ]
    elif schema.get("enum"):
        values = [FactorValue(f"enum:{value}", deepcopy(value)) for value in schema["enum"]]
    else:
        schema_type = schema.get("type")
        nullable = isinstance(schema_type, list) and "null" in schema_type
        if isinstance(schema_type, list):
            schema_type = next((item for item in schema_type if item != "null"), "null")
        if schema_type == "boolean":
            values = [FactorValue("true", True), FactorValue("false", False)]
        elif schema_type in {"integer", "number"}:
            if "multipleOf" in schema:
                return []
            minimum = schema.get("minimum", 0)
            maximum = schema.get("maximum", minimum + 10)
            if "exclusiveMinimum" in schema and not isinstance(schema["exclusiveMinimum"], bool):
                minimum = schema["exclusiveMinimum"] + (1 if schema_type == "integer" else 0.1)
            if "exclusiveMaximum" in schema and not isinstance(schema["exclusiveMaximum"], bool):
                maximum = schema["exclusiveMaximum"] - (1 if schema_type == "integer" else 0.1)
            typical = (
                (minimum + maximum) // 2 if schema_type == "integer" else (minimum + maximum) / 2
            )
            values = [
                FactorValue("minimum", minimum),
                FactorValue("typical", typical),
                FactorValue("maximum", maximum),
            ]
        elif schema_type == "string":
            if schema.get("format"):
                values = [
                    FactorValue(
                        f"format-variant-{index + 1}",
                        synthetic_value(contract, schema, field_name=field, variant=index),
                    )
                    for index in range(3)
                ]
            else:
                minimum = int(schema.get("minLength", 1))
                maximum = int(schema.get("maxLength", max(minimum, 8)))
                typical = min(maximum, max(minimum, (minimum + maximum) // 2))
                values = [
                    FactorValue("minimum-length", "x" * minimum),
                    FactorValue("typical-length", "x" * typical),
                    FactorValue("maximum-length", "x" * maximum),
                ]
        elif schema_type == "array":
            minimum = int(schema.get("minItems", 0))
            maximum = int(schema.get("maxItems", max(minimum, 3)))
            typical = min(maximum, max(minimum, (minimum + maximum) // 2))

            def items(count: int) -> list[Any]:
                return [
                    synthetic_value(
                        contract,
                        schema.get("items") or {},
                        field_name=field,
                        variant=index if schema.get("uniqueItems") else 0,
                    )
                    for index in range(count)
                ]

            values = [
                FactorValue("minimum-items", items(minimum)),
                FactorValue("typical-items", items(typical)),
                FactorValue("maximum-items", items(maximum)),
            ]
        else:
            values = []
        if nullable:
            values.append(FactorValue("null", None))
    return values


def _covering_rows(factors: list[PairwiseFactor], limit: int) -> tuple[list[tuple[int, ...]], int]:
    required = _required_pair_ids(factors)
    rows: list[tuple[int, ...]] = [
        (left, right)
        for left, right in product(range(len(factors[0].values)), range(len(factors[1].values)))
    ]
    rows = rows[:limit]
    for factor_index in range(2, len(factors)):
        grown: list[tuple[int, ...]] = []
        uncovered = required - {
            pair for row in rows for pair in _row_pair_ids(factors[:factor_index], row)
        }
        for row in rows:
            best_value = max(
                range(len(factors[factor_index].values)),
                key=lambda value: (
                    len(_row_pair_ids(factors[: factor_index + 1], (*row, value)) & uncovered),
                    -value,
                ),
            )
            grown_row = (*row, best_value)
            grown.append(grown_row)
            uncovered -= _row_pair_ids(factors[: factor_index + 1], grown_row)
        rows = grown
        relevant = sorted(pair for pair in uncovered if f"|{factor_index}:" in pair)
        for pair in relevant:
            if pair not in uncovered:
                continue
            if len(rows) >= limit:
                break
            left, right = _parse_pair_id(pair)
            row = [0] * (factor_index + 1)
            row[left[0]] = left[1]
            row[right[0]] = right[1]
            candidate = tuple(row)
            rows.append(candidate)
            uncovered -= _row_pair_ids(factors[: factor_index + 1], candidate)
    return rows[:limit], len(required)


def _required_pair_ids(factors: list[PairwiseFactor]) -> set[str]:
    return {
        _pair_id(left_index, left_value, right_index, right_value)
        for left_index in range(len(factors))
        for right_index in range(left_index + 1, len(factors))
        for left_value in range(len(factors[left_index].values))
        for right_value in range(len(factors[right_index].values))
    }


def _row_pair_ids(factors: list[PairwiseFactor], row: tuple[int, ...]) -> set[str]:
    return {
        _pair_id(left, row[left], right, row[right])
        for left in range(len(row))
        for right in range(left + 1, len(row))
    }


def _pair_id(left_factor: int, left_value: int, right_factor: int, right_value: int) -> str:
    return f"{left_factor}:{left_value}|{right_factor}:{right_value}"


def _parse_pair_id(value: str) -> tuple[tuple[int, int], tuple[int, int]]:
    left, right = value.split("|", 1)
    return tuple(map(int, left.split(":"))), tuple(map(int, right.split(":")))  # type: ignore[return-value]


def _apply_row(
    base: dict[str, Any],
    path_template: str,
    factors: list[PairwiseFactor],
    row: tuple[int, ...],
) -> dict[str, Any]:
    request = deepcopy(base)
    split = urlsplit(request["path"])
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    path_parts = path_template.strip("/").split("/")
    current_parts = split.path.strip("/").split("/")
    for factor, value_index in zip(factors, row, strict=True):
        value = factor.values[value_index].value
        if factor.location == "body":
            if factor.field == "$variant":
                request["body"] = deepcopy(value)
            elif value is ABSENT:
                request["body"].pop(factor.field, None)
            else:
                request["body"][factor.field] = deepcopy(value)
        elif factor.location == "query":
            query.pop(factor.field, None) if value is ABSENT else query.__setitem__(
                factor.field, _text(value)
            )
        elif factor.location == "header":
            headers = request.setdefault("headers", {})
            headers.pop(factor.field, None) if value is ABSENT else headers.__setitem__(
                factor.field, _text(value)
            )
        elif factor.location == "path":
            current_parts = [
                quote(_text(value), safe="") if part == f"{{{factor.field}}}" else current
                for part, current in zip(path_parts, current_parts, strict=True)
            ]
    request["path"] = urlunsplit(
        ("", "", f"/{'/'.join(current_parts)}", urlencode(sorted(query.items())), "")
    )
    return request


def _fingerprint(value: Any) -> str:
    if value is ABSENT:
        return "<absent>"
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _resolve_schema(contract: dict[str, Any], value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return {}
    if isinstance(value, list):
        return [_resolve_schema(contract, item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    resolved = resolve_ref(contract, value)
    return {key: _resolve_schema(contract, item, depth + 1) for key, item in resolved.items()}
