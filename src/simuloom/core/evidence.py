from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jsonschema import ValidationError, validate

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.cases import baseline_contract_cases
from simuloom.core.compiler import resolve_ref
from simuloom.core.contracts import (
    analyze_contract,
    is_eligibility_contract,
    iter_operations,
    operation_identifier,
)
from simuloom.core.repository import WorkspaceRepository
from simuloom.models import (
    CoverageMetric,
    EvidenceReport,
    ValidationCaseResult,
    ValidationSummary,
)


@dataclass(slots=True)
class ValidationCase:
    name: str
    category: str
    operation_id: str
    method: str
    path: str
    expected_status: int
    body: Any = None
    headers: dict[str, str] | None = None
    response_schema: dict[str, Any] | None = None


def _operation(contract: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    for path, _, method, operation in iter_operations(contract):
        if operation_identifier(method, path, operation) == operation_id:
            return operation
    return None


def _resolve_refs(value: Any, root: dict[str, Any], depth: int = 0) -> Any:
    if depth > 12:
        return {}
    if isinstance(value, list):
        return [_resolve_refs(item, root, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        return _resolve_refs(resolve_ref(root, value), root, depth + 1)
    return {key: _resolve_refs(item, root, depth + 1) for key, item in value.items()}


def _response_schema(
    contract: dict[str, Any], operation_id: str, status: int
) -> dict[str, Any] | None:
    operation = _operation(contract, operation_id)
    if operation is None:
        return None
    responses = operation.get("responses") or {}
    response = responses.get(str(status))
    if response is None:
        response = next(
            (
                value
                for code, value in responses.items()
                if str(code).upper() == f"{str(status)[0]}XX"
            ),
            responses.get("default", {}),
        )
    response = _resolve_refs(response or {}, contract)
    content = response.get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), {})
    schema = media.get("schema")
    return _resolve_refs(schema, contract) if isinstance(schema, dict) else None


def build_validation_cases(
    contract: dict[str, Any],
    members: list[dict[str, Any]],
    profile: dict[str, Any],
    max_dataset_cases: int,
    contract_cases: list[dict[str, Any]] | None = None,
) -> list[ValidationCase]:
    if not is_eligibility_contract(contract):
        return _build_generic_validation_cases(
            contract, contract_cases or [], profile, max_dataset_cases
        )
    return _build_eligibility_validation_cases(contract, members, profile, max_dataset_cases)


def _build_eligibility_validation_cases(
    contract: dict[str, Any],
    members: list[dict[str, Any]],
    profile: dict[str, Any],
    max_dataset_cases: int,
) -> list[ValidationCase]:
    profile_name = profile["name"]
    failure_status = profile["failureStatus"]
    eligibility_schema = _response_schema(contract, "checkEligibility", 200)
    request_schema = _response_schema(contract, "beginEligibilityRequest", 202)
    status_schema = _response_schema(contract, "getEligibilityRequest", 200)
    selected_members = members[:max_dataset_cases] or [{"memberId": "SYN-1207-000001"}]
    cases: list[ValidationCase] = []

    for index, member in enumerate(selected_members, start=1):
        path = f"/eligibility/{member['memberId']}"
        if profile_name == "unavailable":
            cases.append(
                ValidationCase(
                    f"member lookup {index} unavailable",
                    "profile",
                    "checkEligibility",
                    "GET",
                    path,
                    failure_status,
                )
            )
        elif profile_name == "intermittent":
            cases.extend(
                (
                    ValidationCase(
                        f"member lookup {index} normal",
                        "dataset",
                        "checkEligibility",
                        "GET",
                        path,
                        200,
                        response_schema=eligibility_schema,
                    ),
                    ValidationCase(
                        f"member lookup {index} intermittent failure",
                        "profile",
                        "checkEligibility",
                        "GET",
                        path,
                        failure_status,
                    ),
                )
            )
        else:
            cases.append(
                ValidationCase(
                    f"member lookup {index}",
                    "dataset",
                    "checkEligibility",
                    "GET",
                    path,
                    200,
                    response_schema=eligibility_schema,
                )
            )

    if profile_name == "unavailable":
        negative_statuses = [failure_status]
    elif profile_name == "intermittent":
        negative_statuses = [404, failure_status]
    else:
        negative_statuses = [404]
    for index, expected in enumerate(negative_statuses, start=1):
        cases.append(
            ValidationCase(
                f"unknown member response {index}",
                "negative" if expected == 404 else "profile",
                "checkEligibility",
                "GET",
                "/eligibility/UNKNOWN-SYNTHETIC",
                expected,
            )
        )

    journey_expected = failure_status if profile_name == "unavailable" else None
    cases.extend(
        (
            ValidationCase(
                "submit eligibility request",
                "journey",
                "beginEligibilityRequest",
                "POST",
                "/eligibility/requests",
                journey_expected or 202,
                body={"memberId": selected_members[0]["memberId"]},
                response_schema=None if journey_expected else request_schema,
            ),
            ValidationCase(
                "eligibility request processing",
                "journey",
                "getEligibilityRequest",
                "GET",
                "/eligibility/requests/REQ-SYN-001",
                journey_expected or 200,
                response_schema=None if journey_expected else status_schema,
            ),
            ValidationCase(
                "eligibility request completed",
                "journey",
                "getEligibilityRequest",
                "GET",
                "/eligibility/requests/REQ-SYN-001",
                journey_expected or 200,
                response_schema=None if journey_expected else status_schema,
            ),
        )
    )
    return cases


def _build_generic_validation_cases(
    contract: dict[str, Any],
    stored_cases: list[dict[str, Any]],
    profile: dict[str, Any],
    max_dataset_cases: int,
) -> list[ValidationCase]:
    selected = stored_cases[:max_dataset_cases]
    covered_operations = {case["operationId"] for case in selected}
    generated_baselines = [
        case
        for case in baseline_contract_cases(contract)
        if case["operationId"] not in covered_operations
    ]
    source_cases = [*selected, *generated_baselines]
    profile_name = profile["name"]
    failure_status = profile["failureStatus"]
    planned: list[ValidationCase] = []
    for case in source_cases:
        expected_status = int(case["expectedStatus"])
        response_schema = _response_schema(contract, case["operationId"], expected_status)
        category = "dataset" if case in selected else "contract"
        normal = ValidationCase(
            name=f"{case['operationId']} synthetic request",
            category=category,
            operation_id=case["operationId"],
            method=case["method"],
            path=case["path"],
            expected_status=expected_status,
            body=case.get("body"),
            headers=case.get("headers") or None,
            response_schema=response_schema,
        )
        if profile_name == "unavailable":
            planned.append(
                ValidationCase(
                    name=f"{case['operationId']} unavailable",
                    category="profile",
                    operation_id=case["operationId"],
                    method=case["method"],
                    path=case["path"],
                    expected_status=failure_status,
                    body=case.get("body"),
                    headers=case.get("headers") or None,
                )
            )
        elif profile_name == "intermittent":
            planned.extend(
                (
                    normal,
                    ValidationCase(
                        name=f"{case['operationId']} intermittent failure",
                        category="profile",
                        operation_id=case["operationId"],
                        method=case["method"],
                        path=case["path"],
                        expected_status=failure_status,
                        body=case.get("body"),
                        headers=case.get("headers") or None,
                    ),
                )
            )
        else:
            planned.append(normal)
    return planned


def _coverage(covered: int, total: int) -> CoverageMetric:
    percentage = round((covered / total * 100) if total else 100.0, 2)
    return CoverageMetric(covered=covered, total=total, percentage=percentage)


def render_html(report: EvidenceReport) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(result.name)}</td>"
        f"<td>{html.escape(result.operation_id)}</td>"
        f"<td>{result.expected_status}</td>"
        f"<td>{result.actual_status if result.actual_status is not None else '-'}</td>"
        f"<td class={'pass' if result.passed else 'fail'}>"
        f"{'PASS' if result.passed else 'FAIL'}</td>"
        f"<td>{html.escape('; '.join(result.errors))}</td>"
        "</tr>"
        for result in report.results
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>SimuLoom Evidence</title>
<style>
body{{font-family:Arial,sans-serif;margin:32px;color:#172033}}
.cards{{display:flex;gap:16px}}
.card{{background:#f3f6fb;padding:16px;border-radius:10px;min-width:140px}}
table{{width:100%;border-collapse:collapse;margin-top:24px}}
th,td{{border:1px solid #d8deea;padding:9px;text-align:left}}
th{{background:#172033;color:white}}
.pass{{color:#08783e;font-weight:bold}} .fail{{color:#b42318;font-weight:bold}}
</style></head><body><h1>SimuLoom Validation Evidence</h1>
<p>Simulation: <strong>{html.escape(report.simulation_id)}</strong><br>
Profile: <strong>{html.escape(report.active_profile)}</strong></p>
<div class="cards"><div class="card">Status<br><strong>{report.status.upper()}</strong></div>
<div class="card">Tests<br><strong>{report.summary.passed}/{report.summary.total}</strong></div>
<div class="card">Operations<br><strong>{report.operation_coverage.percentage}%</strong></div>
<div class="card">Unmatched<br><strong>{report.summary.unmatched_requests}</strong></div></div>
<table><thead><tr><th>Case</th><th>Operation</th><th>Expected</th>
<th>Actual</th><th>Result</th><th>Errors</th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""


class EvidenceEngine:
    def __init__(self, repository: WorkspaceRepository, wiremock: WireMockClient):
        self.repository = repository
        self.wiremock = wiremock

    async def run(
        self, simulation_id: str, max_dataset_cases: int, reset_runtime_state: bool
    ) -> EvidenceReport:
        contract = self.repository.read_json(simulation_id, "contract.json")
        simulation = self.repository.read_json(simulation_id, "simulation.json")
        try:
            members = self.repository.read_json(simulation_id, "datasets/members.json")
        except FileNotFoundError:
            members = []
        try:
            contract_cases = self.repository.read_json(simulation_id, "datasets/cases.json")
        except FileNotFoundError:
            contract_cases = []
        try:
            profile = self.repository.read_json(simulation_id, "behavior/profile.json")
        except FileNotFoundError:
            profile = {"name": "normal", "fixedDelayMs": 2_000, "failureStatus": 503}

        if reset_runtime_state:
            await self.wiremock.reset_runtime_state()
        cases = build_validation_cases(
            contract, members, profile, max_dataset_cases, contract_cases
        )
        results: list[ValidationCaseResult] = []
        for case in cases:
            errors: list[str] = []
            actual_status: int | None = None
            elapsed_ms: float | None = None
            schema_valid: bool | None = None
            try:
                observation = await self.wiremock.execute(
                    case.method, case.path, case.body, case.headers
                )
                actual_status = observation.status_code
                elapsed_ms = observation.elapsed_ms
                if actual_status != case.expected_status:
                    errors.append(f"Expected HTTP {case.expected_status}, received {actual_status}")
                if case.response_schema is not None and actual_status == case.expected_status:
                    try:
                        validate(instance=observation.body, schema=case.response_schema)
                        schema_valid = True
                    except ValidationError as exc:
                        schema_valid = False
                        errors.append(f"Schema validation failed: {exc.message}")
            except Exception as exc:
                errors.append(f"Execution failed: {exc}")
            results.append(
                ValidationCaseResult(
                    name=case.name,
                    category=case.category,
                    operation_id=case.operation_id,
                    method=case.method,
                    path=case.path,
                    expected_status=case.expected_status,
                    actual_status=actual_status,
                    response_time_ms=elapsed_ms,
                    schema_valid=schema_valid,
                    passed=not errors,
                    errors=errors,
                )
            )

        events = await self.wiremock.serve_events()
        unmatched = sum(1 for event in events if event.get("wasMatched") is False)
        passed = sum(1 for result in results if result.passed)
        operations = analyze_contract(contract).operations
        executed_operations = {result.operation_id for result in results}
        scenario_names = {result.category for result in results}
        passed_scenarios = {
            category
            for category in scenario_names
            if all(result.passed for result in results if result.category == category)
        }
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_id = f"evidence-{timestamp}-{uuid.uuid4().hex[:6]}"
        report = EvidenceReport(
            report_id=report_id,
            simulation_id=simulation_id,
            generated_at=datetime.now(UTC),
            contract_fingerprint=simulation["fingerprint"],
            active_profile=profile["name"],
            status="passed" if passed == len(results) and unmatched == 0 else "failed",
            summary=ValidationSummary(
                total=len(results),
                passed=passed,
                failed=len(results) - passed,
                unmatched_requests=unmatched,
            ),
            operation_coverage=_coverage(
                len(executed_operations & {item.operation_id for item in operations}),
                len(operations),
            ),
            scenario_coverage=_coverage(len(passed_scenarios), len(scenario_names)),
            results=results,
            artifacts={"json": "reports/latest.json", "html": "reports/latest.html"},
        )
        payload = report.model_dump(mode="json")
        self.repository.write_json(simulation_id, f"reports/{report_id}.json", payload)
        self.repository.write_json(simulation_id, "reports/latest.json", payload)
        self.repository.write_text(simulation_id, "reports/latest.html", render_html(report))
        return report
