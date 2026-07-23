from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from jsonschema import ValidationError, validate

from simuloom.adapters.wiremock import RuntimeResponse, WireMockClient
from simuloom.core.edge_cases import compile_edge_case_mappings, generate_edge_cases
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


def edge_contract(include_error: bool = True) -> dict:
    responses: dict[str, dict] = {
        "201": {
            "description": "created",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    }
                }
            },
        }
    }
    if include_error:
        responses["400"] = {
            "description": "invalid request",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"code": {"type": "string", "const": "INVALID"}},
                        "required": ["code"],
                    }
                }
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Edge API", "version": "1"},
        "paths": {
            "/widgets": {
                "post": {
                    "operationId": "createWidget",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1, "maximum": 5},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name", "tier"],
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "minLength": 2,
                                            "maxLength": 4,
                                        },
                                        "tier": {
                                            "type": "string",
                                            "enum": ["basic", "premium"],
                                        },
                                        "quantity": {
                                            "type": "integer",
                                            "minimum": 1,
                                            "maximum": 10,
                                        },
                                        "tags": {
                                            "type": "array",
                                            "minItems": 1,
                                            "maxItems": 2,
                                            "items": {"type": "string"},
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": responses,
                }
            }
        },
    }


def test_generates_deterministic_boundary_and_negative_cases() -> None:
    first = generate_edge_cases(edge_contract(), max_per_operation=100)
    second = generate_edge_cases(edge_contract(), max_per_operation=100)

    assert first == second
    assert {case["edge"]["polarity"] for case in first} == {"boundary", "negative"}
    assert {case["edge"]["constraint"] for case in first} >= {
        "required",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "enum",
        "type",
    }
    assert all(
        case["expectedStatus"] == 400 for case in first if case["edge"]["polarity"] == "negative"
    )
    assert all(
        case["expectedStatus"] == 201 for case in first if case["edge"]["polarity"] == "boundary"
    )


def test_negative_cases_require_documented_error_response() -> None:
    cases = generate_edge_cases(edge_contract(include_error=False), max_per_operation=100)

    assert cases
    assert {case["edge"]["polarity"] for case in cases} == {"boundary"}


def test_respects_per_operation_cap_and_mode_selection() -> None:
    cases = generate_edge_cases(
        edge_contract(), include_boundary=False, include_negative=True, max_per_operation=3
    )

    assert len(cases) == 3
    assert all(case["edge"]["polarity"] == "negative" for case in cases)


def test_compiles_precise_priority_two_mappings() -> None:
    cases = generate_edge_cases(edge_contract(), max_per_operation=100)
    mappings = compile_edge_case_mappings(cases)

    assert mappings
    assert all(mapping["priority"] == 2 for mapping in mappings)
    assert all(mapping["metadata"]["simuloomEdgeCase"] is True for mapping in mappings)
    missing_query = next(
        mapping
        for mapping in mappings
        if mapping["metadata"]["simuloomConstraint"] == "required"
        and mapping["metadata"]["simuloomField"] == "limit"
    )
    assert missing_query["request"]["queryParameters"]["limit"] == {"absent": True}


def test_validation_plan_is_opt_in_and_exposes_constraint_metadata(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Edge Plan", edge_contract())

    baseline = service.plan_validation(simulation.id, 3)
    expanded = service.plan_validation(
        simulation.id,
        3,
        include_boundary_cases=True,
        include_negative_cases=True,
        max_edge_cases_per_operation=50,
    )

    assert all(case.edge_polarity is None for case in baseline.cases)
    edge_cases = [case for case in expanded.cases if case.edge_polarity is not None]
    assert {case.edge_polarity for case in edge_cases} == {"boundary", "negative"}
    assert all(
        case.edge_constraint and case.edge_location and case.edge_field for case in edge_cases
    )


class EdgeWireMock:
    base_url = "http://wiremock.test"

    async def reset_runtime_state(self) -> None:
        return None

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> RuntimeResponse:
        del method, headers
        query = parse_qs(urlsplit(path).query)
        valid = query.get("limit") in ([str(value)] for value in range(1, 6))
        try:
            schema = edge_contract()["paths"]["/widgets"]["post"]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            validate(json_body, schema)
        except ValidationError:
            valid = False
        body = {"id": "SYN-WIDGET-001"} if valid else {"code": "INVALID"}
        return RuntimeResponse(201 if valid else 400, body, {}, 1.0)

    async def serve_events(self) -> list[dict[str, Any]]:
        return []


@pytest.mark.asyncio
async def test_edge_evidence_reports_boundary_and_negative_coverage(tmp_path: Path) -> None:
    service = SimulationService(WorkspaceRepository(tmp_path), EdgeWireMock())  # type: ignore[arg-type]
    simulation = service.create("Edge Evidence", edge_contract())
    service.compile(simulation.id)
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(
        simulation.id,
        3,
        True,
        include_boundary_cases=True,
        include_negative_cases=True,
        max_edge_cases_per_operation=50,
    )

    assert report.status == "passed"
    assert report.boundary_coverage.percentage == 100.0
    assert report.negative_coverage.percentage == 100.0
    assert report.boundary_coverage.total > 0
    assert report.negative_coverage.total > 0
