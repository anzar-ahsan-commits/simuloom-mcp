import pytest
from pydantic import ValidationError

from simuloom.core.scenarios import compile_scenario_mappings, validate_scenario_contract
from simuloom.models import ScenarioDefinition


def contract() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Orders", "version": "1"},
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["status"],
                                        "properties": {"status": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/orders/{orderId}": {
                "get": {
                    "operationId": "getOrder",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }


def definition_payload() -> dict:
    return {
        "name": "Order lifecycle",
        "description": "Create and inspect an order",
        "initial_state": "NEW",
        "reset": {"target_state": "NEW"},
        "states": [
            {
                "name": "NEW",
                "handlers": [
                    {
                        "name": "create",
                        "request": {
                            "method": "POST",
                            "path": "/orders",
                            "json_body": {"item": "SYN-1"},
                        },
                        "response": {"status": 201, "json_body": {"status": "PENDING"}},
                        "new_state": "PENDING",
                    }
                ],
            },
            {
                "name": "PENDING",
                "handlers": [
                    {
                        "name": "inspect",
                        "request": {"method": "GET", "path": "/orders/ORD-SYN-1"},
                        "response": {"status": 200, "json_body": {"status": "PENDING"}},
                    }
                ],
            },
        ],
    }


def test_scenario_model_validates_state_graph() -> None:
    definition = ScenarioDefinition.model_validate(definition_payload())

    assert definition.initial_state == "NEW"
    assert definition.reset_state == "NEW"

    invalid = definition_payload()
    invalid["states"][0]["handlers"][0]["new_state"] = "MISSING"
    with pytest.raises(ValidationError, match="unknown state"):
        ScenarioDefinition.model_validate(invalid)


def test_scenario_model_rejects_unsafe_response_headers() -> None:
    invalid = definition_payload()
    invalid["states"][0]["handlers"][0]["response"]["headers"] = {"Content-Length": "2"}

    with pytest.raises(ValidationError, match="unsafe headers"):
        ScenarioDefinition.model_validate(invalid)


def test_scenario_contract_validation_rejects_unapproved_operations() -> None:
    definition = ScenarioDefinition.model_validate(definition_payload())
    definition.states[0].handlers[0].request.path = "/__admin/mappings"

    with pytest.raises(ValueError, match="approved OpenAPI operation"):
        validate_scenario_contract(contract(), definition)


def test_scenario_compiles_wiremock_transitions_deterministically() -> None:
    definition = ScenarioDefinition.model_validate(definition_payload())
    validate_scenario_contract(contract(), definition)

    first = compile_scenario_mappings("orders-1234", "order-lifecycle", definition)
    second = compile_scenario_mappings("orders-1234", "order-lifecycle", definition)

    assert first == second
    assert len(first) == 2
    assert first[0]["scenarioName"] == "SimuLoom:orders-1234:order-lifecycle"
    assert first[0]["requiredScenarioState"] == "NEW"
    assert first[0]["newScenarioState"] == "PENDING"
    assert first[0]["request"]["bodyPatterns"][0]["equalToJson"] == '{"item":"SYN-1"}'
    assert first[1]["requiredScenarioState"] == "PENDING"
    assert "newScenarioState" not in first[1]


def test_scenario_fault_and_delay_compile_for_wiremock() -> None:
    payload = definition_payload()
    payload["states"][0]["handlers"][0]["response"]["delay_ms"] = 125
    payload["states"][0]["handlers"][0]["response"]["fault"] = "connection-reset"
    definition = ScenarioDefinition.model_validate(payload)

    mapping = compile_scenario_mappings("orders-1234", "faults", definition)[0]

    assert mapping["response"]["fixedDelayMilliseconds"] == 125
    assert mapping["response"]["fault"] == "CONNECTION_RESET_BY_PEER"
    assert "body" not in mapping["response"]


class ScenarioWireMock:
    base_url = "http://wiremock.test"

    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.deployed: list[dict] = []

    async def scenario_state(self, name: str) -> str | None:
        return self.states.get(name)

    async def deploy_scenario(
        self,
        mappings: list[dict],
        name: str,
        initial: str,
        simulation_id: str | None = None,
    ) -> int:
        self.deployed = mappings
        self.states[name] = initial
        return len(mappings)

    async def set_scenario_state(self, name: str, state: str) -> None:
        self.states[name] = state

    async def reset_all_scenarios(self) -> None:
        self.states = {name: "Started" for name in self.states}


@pytest.mark.asyncio
async def test_scenario_service_persists_deploys_and_resets(tmp_path) -> None:
    from simuloom.core.repository import WorkspaceRepository
    from simuloom.core.service import SimulationService

    wiremock = ScenarioWireMock()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Order scenarios", contract())
    definition = ScenarioDefinition.model_validate(definition_payload())

    configured = service.configure_scenario(simulation.id, "order-lifecycle", definition)
    compiled = service.compile_scenario(simulation.id, "order-lifecycle")
    whole_simulation = service.compile(simulation.id)
    deployed = await service.deploy_scenario(simulation.id, "order-lifecycle")
    state = await service.scenario_state(simulation.id, "order-lifecycle")

    assert configured.definition.name == "Order lifecycle"
    assert compiled.mapping_count == 2
    assert whole_simulation.stateful_mapping_count == 2
    assert deployed.current_state == "NEW"
    assert deployed.release_number == 1
    assert deployed.revision == 1
    assert state.deployed is True

    wiremock.states[compiled.wiremock_scenario_name] = "PENDING"
    reset = await service.reset_scenario(simulation.id, "order-lifecycle")
    assert reset.current_state == "NEW"

    wiremock.states[compiled.wiremock_scenario_name] = "PENDING"
    reset_all = await service.reset_all_scenarios()
    assert reset_all.reset_scenarios == 1


@pytest.mark.asyncio
async def test_exact_revision_deployment_history_and_rollback(tmp_path) -> None:
    from simuloom.core.repository import WorkspaceRepository
    from simuloom.core.service import SimulationService

    wiremock = ScenarioWireMock()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Release management", contract())
    first = ScenarioDefinition.model_validate(definition_payload())
    configured = service.configure_scenario(simulation.id, "order-lifecycle", first)
    release_one = await service.deploy_scenario(
        simulation.id, "order-lifecycle", actor="release-operator"
    )
    changed_payload = definition_payload()
    changed_payload["states"][0]["handlers"][0]["response"]["json_body"] = {"status": "REVISED"}
    second = service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(changed_payload),
        expected_etag=configured.etag,
    )
    release_two = await service.deploy_scenario(
        simulation.id, "order-lifecycle", actor="release-operator"
    )
    rollback = await service.rollback_scenario_release(
        simulation.id, "order-lifecycle", 1, "rollback-operator"
    )
    releases = service.scenario_releases(simulation.id, "order-lifecycle")

    assert release_one.release_number == 1
    assert release_two.release_number == 2
    assert release_two.revision == second.revision == 2
    assert release_one.mapping_fingerprint != release_two.mapping_fingerprint
    assert rollback.release_number == 3
    assert rollback.revision == 1
    assert rollback.mapping_fingerprint == release_one.mapping_fingerprint
    assert [release.release_number for release in releases] == [3, 2, 1]
    assert releases[0].source_release == 1
    assert releases[0].deployed_by == "rollback-operator"
    assert wiremock.deployed[0].response.json_body["status"] == "PENDING"


@pytest.mark.asyncio
async def test_virtual_clock_applies_timeout_transitions(tmp_path) -> None:
    from simuloom.core.repository import WorkspaceRepository
    from simuloom.core.service import SimulationService

    wiremock = ScenarioWireMock()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Virtual time", contract())
    payload = definition_payload()
    payload["states"][0]["timeout_ms"] = 1000
    payload["states"][0]["timeout_state"] = "PENDING"
    service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(payload),
    )
    await service.deploy_scenario(simulation.id, "order-lifecycle")

    before = await service.advance_scenario_clock(
        simulation.id, "order-lifecycle", 999, "clock-user"
    )
    after = await service.advance_scenario_clock(simulation.id, "order-lifecycle", 1, "clock-user")

    assert before.current_state == "NEW"
    assert before.elapsed_ms == 999
    assert after.current_state == "PENDING"
    assert after.transitions_applied == ["PENDING"]
    assert after.elapsed_ms == 0


@pytest.mark.asyncio
async def test_inbound_event_transitions_deployed_scenario(tmp_path) -> None:
    from simuloom.core.repository import WorkspaceRepository
    from simuloom.core.service import SimulationService

    service = SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]
    simulation = service.create("Event orchestration", contract())
    payload = definition_payload()
    payload["states"][0]["event_transitions"] = [
        {"topic": "orders.accepted", "new_state": "PENDING"}
    ]
    service.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(payload),
    )
    await service.deploy_scenario(simulation.id, "order-lifecycle")

    result = await service.publish_scenario_event(
        simulation.id, "orders.accepted", {"synthetic": True}, "webhook"
    )
    state = await service.scenario_state(simulation.id, "order-lifecycle")

    assert result.transitioned_scenarios == {"order-lifecycle": "PENDING"}
    assert state.current_state == "PENDING"
    assert service.repository.read_json(simulation.id, f"events/{result.event_id}.json")[
        "payload"
    ] == {"synthetic": True}

    with pytest.raises(ValueError, match="1 MiB"):
        await service.publish_scenario_event(
            simulation.id,
            "orders.accepted",
            "x" * (1024 * 1024 + 1),
            "webhook",
        )


def test_scenario_bundle_round_trip(tmp_path) -> None:
    from simuloom.adapters.wiremock import WireMockClient
    from simuloom.core.repository import WorkspaceRepository
    from simuloom.core.service import SimulationService

    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Portable scenarios", contract())
    definition = ScenarioDefinition.model_validate(definition_payload())
    service.configure_scenario(simulation.id, "order-lifecycle", definition)

    bundle = service.export_bundle_path(simulation.id).read_bytes()
    imported = service.import_bundle(bundle, "scenario.simuloom.zip")
    restored = service.get_scenario(imported.simulation.id, "order-lifecycle")

    assert restored.definition == definition
    assert service.compile_scenario(imported.simulation.id, "order-lifecycle").mapping_count == 2
