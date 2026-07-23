from __future__ import annotations

import json
from typing import Any

from simuloom.runtime.models import (
    RuntimeMapping,
    RuntimeRequestMatcher,
    RuntimeResponseDefinition,
    RuntimeValueMatcher,
)


def from_wiremock_mapping(mapping: dict[str, Any]) -> RuntimeMapping:
    request = mapping.get("request") or {}
    response = mapping.get("response") or {}
    body_patterns = request.get("bodyPatterns") or []
    match_body = bool(body_patterns and "equalToJson" in body_patterns[0])
    body = _json_value(body_patterns[0]["equalToJson"]) if match_body else None
    return RuntimeMapping(
        name=str(mapping.get("name", "SimuLoom mapping")),
        priority=int(mapping.get("priority", 10)),
        request=RuntimeRequestMatcher(
            method=str(request.get("method", "GET")).upper(),
            path=request.get("urlPath"),
            path_pattern=request.get("urlPathPattern"),
            query=_matchers(request.get("queryParameters") or {}),
            headers=_matchers(request.get("headers") or {}),
            match_body=match_body,
            json_body=body,
        ),
        response=RuntimeResponseDefinition(
            status=int(response.get("status", 200)),
            headers={
                str(key): str(value) for key, value in (response.get("headers") or {}).items()
            },
            json_body=_json_value(response.get("body")),
            delay_ms=int(response.get("fixedDelayMilliseconds", 0)),
            fault=response.get("fault"),
        ),
        metadata=mapping.get("metadata") or {},
        scenario_name=mapping.get("scenarioName"),
        required_state=mapping.get("requiredScenarioState"),
        new_state=mapping.get("newScenarioState"),
    )


def to_wiremock_mapping(mapping: RuntimeMapping) -> dict[str, Any]:
    request: dict[str, Any] = {"method": mapping.request.method}
    if mapping.request.path is not None:
        request["urlPath"] = mapping.request.path
    if mapping.request.path_pattern is not None:
        request["urlPathPattern"] = mapping.request.path_pattern
    if mapping.request.query:
        request["queryParameters"] = _wiremock_matchers(mapping.request.query)
    if mapping.request.headers:
        request["headers"] = _wiremock_matchers(mapping.request.headers)
    if mapping.request.match_body:
        request["bodyPatterns"] = [{"equalToJson": json.dumps(mapping.request.json_body)}]
    response: dict[str, Any] = {
        "status": mapping.response.status,
        "headers": mapping.response.headers,
        "body": json.dumps(mapping.response.json_body),
    }
    if mapping.response.delay_ms:
        response["fixedDelayMilliseconds"] = mapping.response.delay_ms
    if mapping.response.fault:
        response.pop("body", None)
        response["fault"] = mapping.response.fault
    payload: dict[str, Any] = {
        "name": mapping.name,
        "priority": mapping.priority,
        "request": request,
        "response": response,
        "metadata": mapping.metadata,
    }
    if mapping.scenario_name is not None:
        payload["scenarioName"] = mapping.scenario_name
    if mapping.required_state is not None:
        payload["requiredScenarioState"] = mapping.required_state
    if mapping.new_state is not None:
        payload["newScenarioState"] = mapping.new_state
    return payload


def from_wiremock_mappings(mappings: list[dict[str, Any]]) -> list[RuntimeMapping]:
    return [from_wiremock_mapping(mapping) for mapping in mappings]


def _matchers(payload: dict[str, Any]) -> dict[str, RuntimeValueMatcher]:
    return {
        str(name): RuntimeValueMatcher(
            equal_to=None if matcher.get("absent") else str(matcher.get("equalTo", "")),
            absent=matcher.get("absent") is True,
        )
        for name, matcher in payload.items()
        if isinstance(matcher, dict)
    }


def _wiremock_matchers(
    matchers: dict[str, RuntimeValueMatcher],
) -> dict[str, dict[str, str | bool]]:
    return {
        name: ({"absent": True} if matcher.absent else {"equalTo": matcher.equal_to or ""})
        for name, matcher in matchers.items()
    }


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value
