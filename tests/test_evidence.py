from pathlib import Path
from typing import Any

import pytest
import yaml

from simuloom.adapters.wiremock import RuntimeResponse
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


class FakeWireMockClient:
    base_url = "http://wiremock.test"

    def __init__(self, invalid_schema: bool = False):
        self.invalid_schema = invalid_schema
        self.journey_state = "SUBMITTED"
        self.reset_called = False

    async def reset_runtime_state(self) -> None:
        self.reset_called = True
        self.journey_state = "SUBMITTED"

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> RuntimeResponse:
        if method == "POST" and path == "/eligibility/requests":
            self.journey_state = "PROCESSING"
            return self._response(
                202,
                {"requestId": "REQ-SYN-001", "status": "SUBMITTED", "synthetic": True},
            )
        if path == "/eligibility/requests/REQ-SYN-001":
            state = self.journey_state
            self.journey_state = "COMPLETED"
            return self._response(
                200, {"requestId": "REQ-SYN-001", "status": state, "synthetic": True}
            )
        if path == "/eligibility/UNKNOWN-SYNTHETIC":
            return self._response(404, {"code": "MEMBER_NOT_FOUND", "synthetic": True})
        member_id = path.rsplit("/", 1)[-1]
        body = {
            "memberId": member_id,
            "status": "ACTIVE",
            "planName": "Synthetic Gold Plan",
            "effectiveDate": "2026-01-01",
            "synthetic": True,
        }
        if self.invalid_schema:
            body.pop("synthetic")
        return self._response(200, body)

    async def serve_events(self) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def _response(status: int, body: dict[str, Any]) -> RuntimeResponse:
        return RuntimeResponse(status, body, {"content-type": "application/json"}, 12.5)


def load_contract() -> dict:
    return yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())


@pytest.mark.asyncio
async def test_evidence_report_passes_and_is_persisted(tmp_path: Path) -> None:
    wiremock = FakeWireMockClient()
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Evidence Demo", load_contract())
    service.generate_data(simulation.id, records=2, seed=77)
    service.compile(simulation.id)
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(simulation.id, max_dataset_cases=2, reset_runtime_state=True)

    assert report.status == "passed"
    assert report.summary.total == 6
    assert report.summary.passed == 6
    assert report.operation_coverage.percentage == 100.0
    assert report.scenario_coverage.percentage == 100.0
    assert wiremock.reset_called is True
    assert service.latest_report(simulation.id).report_id == report.report_id
    assert "SimuLoom Validation Evidence" in service.latest_report_html(simulation.id)


@pytest.mark.asyncio
async def test_schema_failure_is_reported(tmp_path: Path) -> None:
    wiremock = FakeWireMockClient(invalid_schema=True)
    service = SimulationService(WorkspaceRepository(tmp_path), wiremock)  # type: ignore[arg-type]
    simulation = service.create("Invalid Evidence", load_contract())
    service.generate_data(simulation.id, records=1, seed=88)
    service.compile(simulation.id)
    service.repository.update_status(simulation.id, "deployed")

    report = await service.validate(simulation.id, max_dataset_cases=1, reset_runtime_state=True)

    assert report.status == "failed"
    assert report.summary.failed == 1
    failed = next(result for result in report.results if not result.passed)
    assert failed.schema_valid is False
    assert "Schema validation failed" in failed.errors[0]


@pytest.mark.asyncio
async def test_validation_requires_deployment(tmp_path: Path) -> None:
    service = SimulationService(  # type: ignore[arg-type]
        WorkspaceRepository(tmp_path), FakeWireMockClient()
    )
    simulation = service.create("Not Deployed", load_contract())

    with pytest.raises(RuntimeError, match="Deploy this simulation"):
        await service.validate(simulation.id, 1, True)
