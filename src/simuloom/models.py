from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class OperationSummary(BaseModel):
    operation_id: str
    method: str
    path: str
    response_codes: list[str]


class ContractSummary(BaseModel):
    title: str
    version: str
    openapi_version: str
    fingerprint: str
    operations: list[OperationSummary]
    warnings: list[str] = Field(default_factory=list)


class ContractRequest(BaseModel):
    contract: dict[str, Any]


class CreateSimulationRequest(ContractRequest):
    name: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]+$")


class Simulation(BaseModel):
    id: str
    name: str
    fingerprint: str
    status: str
    operation_count: int


class DataGenerationRequest(BaseModel):
    records: int = Field(default=25, ge=1, le=10_000)
    seed: int = 1207


class DataGenerationResult(BaseModel):
    simulation_id: str
    dataset: str
    provider: str
    record_count: int
    seed: int


class DatasetView(BaseModel):
    simulation_id: str
    dataset: str
    provider: str
    synthetic: bool
    record_count: int
    seed: int
    records: list[dict[str, Any]]


class CompileResult(BaseModel):
    simulation_id: str
    mapping_count: int
    contract_mapping_count: int
    dataset_mapping_count: int
    fallback_mapping_count: int
    stateful_mapping_count: int
    active_profile: str
    status: str


class ProfileConfigRequest(BaseModel):
    fixed_delay_ms: int = Field(default=2_000, ge=0, le=60_000)
    failure_status: int = Field(default=503, ge=500, le=599)


class ProfileResult(BaseModel):
    simulation_id: str
    active_profile: Literal["normal", "slow", "unavailable", "intermittent"]
    fixed_delay_ms: int
    failure_status: int
    mapping_count: int
    status: str


class DeployRequest(BaseModel):
    reset_existing: bool = False


class DeployResult(BaseModel):
    simulation_id: str
    wiremock_url: str
    deployed_mappings: int
    status: str


class ValidationRequest(BaseModel):
    max_dataset_cases: int = Field(default=3, ge=1, le=25)
    reset_runtime_state: bool = True


class ValidationPlanRequest(BaseModel):
    max_dataset_cases: int = Field(default=3, ge=1, le=25)


class ValidationPlanCase(BaseModel):
    name: str
    category: str
    operation_id: str
    method: str
    path: str
    expected_status: int
    headers: dict[str, str] | None = None
    body: Any = None
    validates_response_schema: bool


class ValidationPlan(BaseModel):
    simulation_id: str
    active_profile: str
    case_count: int
    cases: list[ValidationPlanCase]


class ValidationCaseResult(BaseModel):
    name: str
    category: str
    operation_id: str
    method: str
    path: str
    expected_status: int
    actual_status: int | None
    response_time_ms: float | None
    schema_valid: bool | None
    passed: bool
    errors: list[str] = Field(default_factory=list)


class CoverageMetric(BaseModel):
    covered: int
    total: int
    percentage: float


class ValidationSummary(BaseModel):
    total: int
    passed: int
    failed: int
    unmatched_requests: int


class EvidenceReport(BaseModel):
    report_id: str
    simulation_id: str
    generated_at: datetime
    contract_fingerprint: str
    active_profile: str
    status: Literal["passed", "failed"]
    summary: ValidationSummary
    operation_coverage: CoverageMetric
    scenario_coverage: CoverageMetric
    results: list[ValidationCaseResult]
    artifacts: dict[str, str]


class ExportResult(BaseModel):
    simulation_id: str
    bundle_name: str
    manifest_version: str
    included_artifacts: list[str]
    manifest_yaml: str


class ImportResult(BaseModel):
    simulation: Simulation
    manifest_version: str
    source_name: str
    imported_dataset_records: int
    active_profile: str
    warnings: list[str] = Field(default_factory=list)
