from pathlib import Path

import yaml

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


def load_contract() -> dict:
    return yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())


def test_create_generate_and_compile(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Eligibility Demo", load_contract())
    generated = service.generate_data(simulation.id, records=5, seed=99)
    compiled = service.compile(simulation.id)

    assert generated.record_count == 5
    assert compiled.mapping_count == 9
    assert compiled.contract_mapping_count == 0
    assert compiled.dataset_mapping_count == 5
    assert compiled.fallback_mapping_count == 1
    assert compiled.stateful_mapping_count == 3
    assert compiled.edge_mapping_count == 0
    assert compiled.active_profile == "normal"
    members = service.repository.read_json(simulation.id, "datasets/members.json")
    assert members[0]["synthetic"] is True
    assert members[0]["memberId"] == "SYN-0099-000001"

    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    exact = mappings[0]
    assert exact["request"]["urlPath"] == "/eligibility/SYN-0099-000001"
    assert exact["response"]["status"] == 200
    assert exact["metadata"]["simuloomDataset"] == "members"

    fallback = next(mapping for mapping in mappings if mapping["metadata"].get("simuloomFallback"))
    assert fallback["request"]["urlPathPattern"] == "^/eligibility/[^/]+$"
    assert fallback["response"]["status"] == 404
    assert fallback["metadata"]["simuloomFallback"] is True


def test_compile_without_dataset_uses_contract_example(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Contract Only", load_contract())

    compiled = service.compile(simulation.id)

    assert compiled.mapping_count == 4
    assert compiled.contract_mapping_count == 1
    assert compiled.dataset_mapping_count == 0
    assert compiled.fallback_mapping_count == 0
    assert compiled.stateful_mapping_count == 3
    assert compiled.edge_mapping_count == 0


def test_slow_profile_adds_delay_to_every_mapping(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Slow Eligibility", load_contract())
    service.generate_data(simulation.id, records=2, seed=7)

    activated = service.activate_profile(simulation.id, "slow", 1_750, 503)

    assert activated.active_profile == "slow"
    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    assert mappings
    assert all(mapping["response"]["fixedDelayMilliseconds"] == 1_750 for mapping in mappings)


def test_unavailable_profile_replaces_responses(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Unavailable Eligibility", load_contract())

    service.activate_profile(simulation.id, "unavailable", 0, 502)

    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    assert all(mapping["response"]["status"] == 502 for mapping in mappings)


def test_intermittent_profile_alternates_stateless_mappings(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Intermittent Eligibility", load_contract())
    service.generate_data(simulation.id, records=2, seed=8)

    activated = service.activate_profile(simulation.id, "intermittent", 0, 503)

    # Three dataset mappings (two members and fallback) are doubled; three journey
    # mappings retain their own state machine.
    assert activated.mapping_count == 9
    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    failures = [
        mapping
        for mapping in mappings
        if mapping.get("metadata", {}).get("simuloomProfile") == "intermittent"
        and mapping["response"]["status"] == 503
    ]
    assert len(failures) == 3
    assert all(mapping["requiredScenarioState"] == "DEGRADED" for mapping in failures)


def test_stateful_journey_progresses_to_completed(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Stateful Eligibility", load_contract())

    service.compile(simulation.id)

    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    journey = [mapping for mapping in mappings if mapping["metadata"].get("simuloomJourney")]
    assert [mapping["metadata"]["simuloomStep"] for mapping in journey] == [
        "SUBMITTED",
        "PROCESSING",
        "COMPLETED",
    ]
    assert journey[0]["newScenarioState"] == "PROCESSING"
    assert journey[1]["newScenarioState"] == "COMPLETED"
