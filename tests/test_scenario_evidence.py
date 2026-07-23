from pathlib import Path
from typing import Any

import pytest

from simuloom.adapters.wiremock import RuntimeResponse
from simuloom.core.evidence import build_scenario_validation_cases
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


def contract() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Evidence Orders", "version": "1"},
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "responses": {"201": {"description": "created"}},
                }
            },
            "/orders/{orderId}": {
                "get": {
                    "operationId": "getOrder",
                    "responses": {"200": {"description": "found"}},
                }
            },
        },
    }


def branching_definition() -> ScenarioDefinition:
    return ScenarioDefinition.model_validate(
        {
            "name": "Branching orders",
            "description": "Covers both reachable branches and reports an orphan state",
            "initial_state": "START",
            "states": [
                {
                    "name": "START",
                    "handlers": [
                        {
                            "name": "go-left",
                            "request": {"method": "POST", "path": "/orders"},
                            "response": {"status": 201},
                            "new_state": "LEFT",
                        },
                        {
                            "name": "go-right",
                            "request": {"method": "POST", "path": "/orders"},
                            "response": {"status": 201},
                            "new_state": "RIGHT",
                        },
                    ],
                },
                {
                    "name": "LEFT",
                    "handlers": [
                        {
                            "name": "inspect-left",
                            "request": {"method": "GET", "path": "/orders/LEFT"},
                            "response": {"status": 200},
                        }
                    ],
                },
                {
                    "name": "RIGHT",
                    "handlers": [
                        {
                            "name": "inspect-right",
                            "request": {"method": "GET", "path": "/orders/RIGHT"},
                            "response": {"status": 200},
                        }
                    ],
                },
                {
                    "name": "ORPHAN",
                    "handlers": [
                        {
                            "name": "inspect-orphan",
                            "request": {"method": "GET", "path": "/orders/ORPHAN"},
                            "response": {"status": 200},
                        }
                    ],
                },
            ],
        }
    )


def test_planner_covers_every_reachable_branch_with_bounded_replay() -> None:
    definition = branching_definition()
    cases = build_scenario_validation_cases(
        contract(), {"branching": definition.model_dump(mode="json")}
    )

    assert {case.scenario_handler for case in cases} >= {
        "go-left",
        "go-right",
        "inspect-left",
        "inspect-right",
    }
    assert all(case.required_state != "ORPHAN" for case in cases)
    assert len(cases) == 6
    assert sum(case.reset_before for case in cases) == 4


class ScenarioEvidenceWireMock:
    base_url = "http://wiremock.test"

    def __init__(self, transition_succeeds: bool = True) -> None:
        self.state: str | None = None
        self.transition_succeeds = transition_succeeds

    async def reset_runtime_state(self) -> None:
        self.state = None

    async def set_scenario_state(self, _name: str, state: str) -> None:
        self.state = state

    async def scenario_state(self, _name: str) -> str | None:
        return self.state

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> RuntimeResponse:
        del json_body, headers
        status = 201 if method == "POST" else 200
        if self.state == "START" and method == "POST" and self.transition_succeeds:
            self.state = "PENDING"
        return RuntimeResponse(status, {}, {}, 1.0)

    async def serve_events(self) -> list[dict[str, Any]]:
        return []


def linear_definition(include_orphan: bool) -> ScenarioDefinition:
    states: list[dict[str, Any]] = [
        {
            "name": "START",
            "handlers": [
                {
                    "name": "create",
                    "request": {"method": "POST", "path": "/orders"},
                    "response": {"status": 201},
                    "new_state": "PENDING",
                }
            ],
        },
        {
            "name": "PENDING",
            "handlers": [
                {
                    "name": "inspect",
                    "request": {"method": "GET", "path": "/orders/ONE"},
                    "response": {"status": 200},
                }
            ],
        },
    ]
    if include_orphan:
        states.append(
            {
                "name": "ORPHAN",
                "handlers": [
                    {
                        "name": "inspect-orphan",
                        "request": {"method": "GET", "path": "/orders/ORPHAN"},
                        "response": {"status": 200},
                    }
                ],
            }
        )
    return ScenarioDefinition.model_validate(
        {
            "name": "Linear evidence",
            "description": "State and transition evidence",
            "initial_state": "START",
            "states": states,
        }
    )


@pytest.mark.asyncio
async def test_unreachable_state_reduces_coverage(tmp_path: Path) -> None:
    wiremock = ScenarioEvidenceWireMock()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Unreachable evidence", contract())
    service.configure_scenario(simulation.id, "linear", linear_definition(include_orphan=True))
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(simulation.id, 3, True)

    assert report.status == "failed"
    assert report.state_coverage.covered == 2
    assert report.state_coverage.total == 3
    assert report.transition_coverage.percentage == 100.0


@pytest.mark.asyncio
async def test_failed_transition_is_reported(tmp_path: Path) -> None:
    wiremock = ScenarioEvidenceWireMock(transition_succeeds=False)
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Failed transition", contract())
    service.configure_scenario(simulation.id, "linear", linear_definition(include_orphan=False))
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(simulation.id, 3, True)

    assert report.status == "failed"
    assert report.transition_coverage.covered == 0
    assert any(
        "Expected scenario transition" in error for item in report.results for error in item.errors
    )
