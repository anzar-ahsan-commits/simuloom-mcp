from inspect import signature
from pathlib import Path
from typing import Any

import pytest
import yaml

from simuloom.adapters.wiremock import RuntimeResponse, WireMockClient
from simuloom.core.pairwise import (
    compile_pairwise_mappings,
    extract_pairwise_factors,
    generate_pairwise_cases,
)
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.mcp.server import plan_validation, run_validation


def load_contract() -> dict:
    return yaml.safe_load(Path("examples/constraint-validation/openapi.yaml").read_text())


def test_pairwise_generation_is_deterministic_and_covers_every_pair() -> None:
    contract = load_contract()

    first = generate_pairwise_cases(contract, max_per_operation=50)
    second = generate_pairwise_cases(contract, max_per_operation=50)

    assert first == second
    assert first
    covered = {pair for case in first for pair in case["pairwise"]["pairIds"]}
    assert len(covered) == first[0]["pairwise"]["totalPairs"]
    assert len(first) < 3 * 2 * 3 * 3 * 3
    assert all(case["expectedStatus"] == 201 for case in first)


def test_low_case_cap_reports_incomplete_pair_coverage() -> None:
    cases = generate_pairwise_cases(load_contract(), max_per_operation=3)

    covered = {pair for case in cases for pair in case["pairwise"]["pairIds"]}
    assert len(cases) == 3
    assert len(covered) < cases[0]["pairwise"]["totalPairs"]


def test_extracts_optional_nullable_boolean_and_union_factors() -> None:
    contract = {
        "components": {
            "schemas": {
                "ChoiceA": {
                    "type": "object",
                    "properties": {"kind": {"type": "string", "const": "A"}},
                }
            }
        }
    }
    operation = {
        "parameters": [
            {
                "name": "enabled",
                "in": "query",
                "required": True,
                "schema": {"type": "boolean"},
            },
            {
                "name": "region",
                "in": "header",
                "required": False,
                "schema": {"type": ["string", "null"], "enum": ["US", "EU", None]},
            },
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/ChoiceA"},
                            {
                                "type": "object",
                                "properties": {"kind": {"type": "string", "const": "B"}},
                            },
                        ]
                    }
                }
            }
        },
    }

    factors = extract_pairwise_factors(contract, {}, operation)

    assert [factor.identity for factor in factors] == [
        "body.$variant",
        "query.enabled",
        "header.region",
    ]
    assert {value.label for value in factors[1].values} == {"true", "false"}
    assert "absent" in {value.label for value in factors[2].values}


def test_pairwise_mappings_are_exact_and_lower_priority_than_edge_cases() -> None:
    cases = generate_pairwise_cases(load_contract(), max_per_operation=10)
    mappings = compile_pairwise_mappings(cases)

    assert mappings
    assert all(mapping["priority"] == 3 for mapping in mappings)
    assert all(mapping["metadata"]["simuloomPairwiseCase"] is True for mapping in mappings)
    assert all("equalToJson" in mapping["request"]["bodyPatterns"][0] for mapping in mappings)


def test_pairwise_validation_plan_is_opt_in(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Pairwise Plan", load_contract())

    baseline = service.plan_validation(simulation.id, 3)
    expanded = service.plan_validation(
        simulation.id,
        3,
        include_pairwise_cases=True,
        max_pairwise_cases_per_operation=50,
    )

    assert all(case.pairwise_assignments is None for case in baseline.cases)
    pairwise = [case for case in expanded.cases if case.pairwise_assignments is not None]
    assert pairwise
    assert all(case.pairwise_pair_ids and case.pairwise_total_pairs for case in pairwise)


def test_mcp_validation_tools_expose_pairwise_options() -> None:
    for tool in (plan_validation, run_validation):
        parameters = signature(tool).parameters
        assert "include_pairwise_cases" in parameters
        assert "max_pairwise_cases_per_operation" in parameters


class PairwiseWireMock:
    base_url = "http://wiremock.test"

    async def reset_runtime_state(self, simulation_id: str | None = None) -> None:
        return None

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        simulation_id: str | None = None,
    ) -> RuntimeResponse:
        del method, path, json_body, headers
        return RuntimeResponse(201, {"id": "SYN-PRODUCT-001", "synthetic": True}, {}, 1.0)

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        return []


@pytest.mark.asyncio
async def test_pairwise_evidence_reports_complete_and_capped_coverage(tmp_path: Path) -> None:
    service = SimulationService(WorkspaceRepository(tmp_path), PairwiseWireMock())  # type: ignore[arg-type]
    simulation = service.create("Pairwise Evidence", load_contract())
    service.repository.update_status(simulation.id, "deployed")

    complete = await service.validate(
        simulation.id,
        3,
        True,
        include_pairwise_cases=True,
        max_pairwise_cases_per_operation=50,
    )
    capped = await service.validate(
        simulation.id,
        3,
        True,
        include_pairwise_cases=True,
        max_pairwise_cases_per_operation=3,
    )

    assert complete.status == "passed"
    assert complete.pairwise_coverage.percentage == 100.0
    assert capped.status == "failed"
    assert capped.pairwise_coverage.percentage < 100.0
