import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from simuloom.adapters.wiremock import RuntimeResponse, WireMockClient
from simuloom.core.cases import generate_contract_cases, validate_contract_cases
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


def load_contract() -> dict:
    return yaml.safe_load(Path("examples/catalog-orders/openapi.yaml").read_text())


def test_generic_cases_are_deterministic_and_schema_driven() -> None:
    contract = load_contract()

    first = generate_contract_cases(contract, records=3, seed=91)
    second = generate_contract_cases(contract, records=3, seed=91)

    assert first == second
    assert [case["operationId"] for case in first] == [
        "getCatalogItem",
        "createOrder",
        "getCatalogItem",
    ]
    assert first[0]["path"].startswith("/catalog/syn-itemid-91-1?locale=en-US")
    assert first[0]["headers"]["X-Tenant-ID"].startswith("syn-x-tenant-id-")
    assert first[1]["body"]["quantity"] == 1
    assert first[1]["body"]["contactEmail"] == "synthetic-91-1@example.test"
    assert all(case["synthetic"] is True for case in first)


def test_generic_case_path_must_match_approved_operation() -> None:
    contract = load_contract()
    cases = generate_contract_cases(contract, records=1, seed=91)
    cases[0]["path"] = "/__admin/mappings"

    with pytest.raises(ValueError, match="does not match operation"):
        validate_contract_cases(contract, cases)


def test_generic_data_compiles_exact_and_fallback_mappings(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Catalog Orders", load_contract())

    generated = service.generate_data(simulation.id, records=3, seed=91)
    compiled = service.compile(simulation.id)
    dataset = service.get_dataset(simulation.id)
    plan = service.plan_validation(simulation.id, max_dataset_cases=3)

    assert generated.dataset == "contract-cases"
    assert generated.provider == "openapi-schema"
    assert dataset.synthetic is True
    assert dataset.record_count == 3
    assert compiled.contract_mapping_count == 2
    assert compiled.dataset_mapping_count == 3
    assert compiled.mapping_count == 32
    assert compiled.edge_mapping_count == 5
    assert compiled.pairwise_mapping_count == 22
    cases = service.repository.read_json(simulation.id, "datasets/cases.json")
    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    exact = next(
        mapping
        for mapping in mappings
        if mapping.get("metadata", {}).get("simuloomRecordId") == cases[0]["caseId"]
    )
    assert exact["request"]["urlPath"].startswith("/catalog/")
    assert exact["request"]["queryParameters"]["locale"] == {"equalTo": "en-US"}
    assert exact["metadata"]["simuloomDataset"] == "contract-cases"
    assert plan.case_count == 3
    assert all(case.validates_response_schema for case in plan.cases)


def test_generic_plan_covers_contract_without_a_dataset(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Contract Only Plan", load_contract())

    plan = service.plan_validation(simulation.id, max_dataset_cases=3)

    assert plan.case_count == 2
    assert {case.operation_id for case in plan.cases} == {
        "getCatalogItem",
        "createOrder",
    }
    assert {case.category for case in plan.cases} == {"contract"}


def test_generic_plan_tracks_active_failure_profile(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("Unavailable Catalog", load_contract())
    service.generate_data(simulation.id, records=2, seed=64)

    service.activate_profile(simulation.id, "unavailable", 0, 502)
    plan = service.plan_validation(simulation.id, max_dataset_cases=2)

    assert plan.active_profile == "unavailable"
    assert {case.expected_status for case in plan.cases} == {502}
    assert {case.category for case in plan.cases} == {"profile"}
    mappings = service.repository.read_json(simulation.id, "mappings/mappings.json")
    assert all(mapping["response"]["status"] == 502 for mapping in mappings)


class GenericWireMockClient:
    base_url = "http://wiremock.test"

    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []

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
        case = next(
            item for item in self.cases if item["method"] == method and item["path"] == path
        )
        assert json_body == case["body"]
        assert (headers or {}) == case["headers"]
        return RuntimeResponse(case["expectedStatus"], case["responseBody"], {}, 4.2)

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        return []


@pytest.mark.asyncio
async def test_generic_validation_covers_every_operation(tmp_path: Path) -> None:
    wiremock = GenericWireMockClient()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Generic Evidence", load_contract())
    service.generate_data(simulation.id, records=2, seed=33)
    service.compile(simulation.id)
    wiremock.cases = service.repository.read_json(simulation.id, "datasets/cases.json")
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(simulation.id, 2, True)

    assert report.status == "passed"
    assert report.summary.total == 2
    assert report.operation_coverage.percentage == 100.0
    assert {result.operation_id for result in report.results} == {
        "getCatalogItem",
        "createOrder",
    }


def test_generic_dataset_bundle_round_trip(tmp_path: Path) -> None:
    service = SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )
    original = service.create("Portable Catalog", load_contract())
    service.generate_data(original.id, records=2, seed=55)

    bundle = service.export_bundle_path(original.id).read_bytes()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = yaml.safe_load(archive.read("simulation.yaml"))
        assert "datasets/cases.json" in archive.namelist()
    assert manifest["spec"]["data"]["provider"] == "openapi-schema"
    assert manifest["spec"]["data"]["path"] == "datasets/cases.json"

    imported = service.import_bundle(bundle, "catalog.simuloom.zip")

    assert imported.imported_dataset_records == 2
    imported_cases = service.repository.read_json(imported.simulation.id, "datasets/cases.json")
    assert [case["operationId"] for case in imported_cases] == [
        "getCatalogItem",
        "createOrder",
    ]
