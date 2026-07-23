from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class SimulationSummary(Simulation):
    active_profile: str
    scenario_count: int = 0
    has_dataset: bool = False
    has_report: bool = False


class SessionView(BaseModel):
    subject: str
    role: Literal["viewer", "operator", "admin"]
    authentication_enabled: bool


class WorkspaceReadiness(BaseModel):
    status: Literal["ready", "degraded"]
    runtime: str
    runtime_ready: bool
    workspace_format: str
    workspace_schema_version: int
    supported_workspace_schema_version: int
    workspace_writable: bool
    simulation_count: int = Field(ge=0)


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
    edge_mapping_count: int = 0
    pairwise_mapping_count: int = 0
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
    include_boundary_cases: bool = False
    include_negative_cases: bool = False
    max_edge_cases_per_operation: int = Field(default=12, ge=1, le=50)
    include_pairwise_cases: bool = False
    max_pairwise_cases_per_operation: int = Field(default=25, ge=1, le=50)


class ValidationPlanRequest(BaseModel):
    max_dataset_cases: int = Field(default=3, ge=1, le=25)
    include_boundary_cases: bool = False
    include_negative_cases: bool = False
    max_edge_cases_per_operation: int = Field(default=12, ge=1, le=50)
    include_pairwise_cases: bool = False
    max_pairwise_cases_per_operation: int = Field(default=25, ge=1, le=50)


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
    scenario_id: str | None = None
    scenario_handler: str | None = None
    required_state: str | None = None
    new_state: str | None = None
    reset_before: bool = False
    edge_polarity: str | None = None
    edge_constraint: str | None = None
    edge_location: str | None = None
    edge_field: str | None = None
    pairwise_assignments: dict[str, str] | None = None
    pairwise_pair_ids: list[str] = Field(default_factory=list)
    pairwise_total_pairs: int = 0


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
    scenario_id: str | None = None
    scenario_handler: str | None = None
    required_state: str | None = None
    new_state: str | None = None
    actual_state_before: str | None = None
    actual_state_after: str | None = None
    edge_polarity: str | None = None
    edge_constraint: str | None = None
    edge_location: str | None = None
    edge_field: str | None = None
    pairwise_assignments: dict[str, str] | None = None
    pairwise_pair_ids: list[str] = Field(default_factory=list)
    pairwise_total_pairs: int = 0


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
    state_coverage: CoverageMetric = Field(
        default_factory=lambda: CoverageMetric(covered=0, total=0, percentage=100.0)
    )
    transition_coverage: CoverageMetric = Field(
        default_factory=lambda: CoverageMetric(covered=0, total=0, percentage=100.0)
    )
    boundary_coverage: CoverageMetric = Field(
        default_factory=lambda: CoverageMetric(covered=0, total=0, percentage=100.0)
    )
    negative_coverage: CoverageMetric = Field(
        default_factory=lambda: CoverageMetric(covered=0, total=0, percentage=100.0)
    )
    pairwise_coverage: CoverageMetric = Field(
        default_factory=lambda: CoverageMetric(covered=0, total=0, percentage=100.0)
    )
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


class ScenarioRequestMatcher(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str = Field(min_length=1, max_length=500)
    query_parameters: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("/__admin"):
            raise ValueError("Scenario request path must be a service-relative non-admin path")
        return value


class ScenarioResponseDefinition(BaseModel):
    status: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any = None
    delay_ms: int = Field(default=0, ge=0, le=60_000)
    fault: Literal["empty-response", "connection-reset", "malformed-response"] | None = None

    @model_validator(mode="after")
    def reject_unsafe_headers(self) -> ScenarioResponseDefinition:
        unsafe = {"connection", "content-length", "transfer-encoding", "upgrade"}
        supplied = {name.lower() for name in self.headers}
        if blocked := sorted(supplied & unsafe):
            raise ValueError(f"Scenario response contains unsafe headers: {', '.join(blocked)}")
        return self


class ScenarioHandler(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
    request: ScenarioRequestMatcher
    response: ScenarioResponseDefinition
    new_state: str | None = Field(default=None, min_length=1, max_length=80)


class ScenarioEventTransition(BaseModel):
    topic: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    new_state: str = Field(min_length=1, max_length=80)


class ScenarioStateDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
    handlers: list[ScenarioHandler] = Field(min_length=1, max_length=50)
    timeout_ms: int | None = Field(default=None, ge=1, le=86_400_000)
    timeout_state: str | None = Field(default=None, min_length=1, max_length=80)
    event_transitions: list[ScenarioEventTransition] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_unique_handlers(self) -> ScenarioStateDefinition:
        names = [handler.name for handler in self.handlers]
        if len(names) != len(set(names)):
            raise ValueError(f"Scenario state '{self.name}' contains duplicate handler names")
        if (self.timeout_ms is None) != (self.timeout_state is None):
            raise ValueError("timeout_ms and timeout_state must be configured together")
        topics = [transition.topic for transition in self.event_transitions]
        if len(topics) != len(set(topics)):
            raise ValueError(f"Scenario state '{self.name}' contains duplicate event topics")
        return self


class ScenarioResetDefinition(BaseModel):
    target_state: str = Field(min_length=1, max_length=80)


class ScenarioDefinition(BaseModel):
    name: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
    description: str = Field(min_length=1, max_length=500)
    initial_state: str = Field(min_length=1, max_length=80)
    states: list[ScenarioStateDefinition] = Field(min_length=1, max_length=50)
    reset: ScenarioResetDefinition | None = None

    @model_validator(mode="after")
    def validate_state_graph(self) -> ScenarioDefinition:
        state_names = [state.name for state in self.states]
        known = set(state_names)
        if len(state_names) != len(known):
            raise ValueError("Scenario contains duplicate state names")
        if self.initial_state not in known:
            raise ValueError("Scenario initial_state must reference a declared state")
        reset_state = self.reset.target_state if self.reset else self.initial_state
        if reset_state not in known:
            raise ValueError("Scenario reset target_state must reference a declared state")
        handlers = [handler for state in self.states for handler in state.handlers]
        if len(handlers) > 200:
            raise ValueError("Scenario cannot contain more than 200 handlers")
        for handler in handlers:
            if handler.new_state is not None and handler.new_state not in known:
                raise ValueError(
                    f"Scenario handler '{handler.name}' references unknown state "
                    f"'{handler.new_state}'"
                )
        for state in self.states:
            if state.timeout_state is not None and state.timeout_state not in known:
                raise ValueError(
                    f"Scenario state '{state.name}' timeout references unknown state "
                    f"'{state.timeout_state}'"
                )
            for transition in state.event_transitions:
                if transition.new_state not in known:
                    raise ValueError(
                        f"Scenario state '{state.name}' event '{transition.topic}' "
                        f"references unknown state '{transition.new_state}'"
                    )
        return self

    @property
    def reset_state(self) -> str:
        return self.reset.target_state if self.reset else self.initial_state


class ScenarioView(BaseModel):
    simulation_id: str
    scenario_id: str
    definition: ScenarioDefinition
    revision: int = 1
    etag: str = ""
    updated_at: datetime | None = None
    updated_by: str | None = None


class ScenarioRevisionSummary(BaseModel):
    revision: int
    etag: str
    created_at: datetime
    created_by: str
    name: str
    state_count: int
    handler_count: int


class ScenarioRevision(ScenarioRevisionSummary):
    simulation_id: str
    scenario_id: str
    definition: ScenarioDefinition


class ScenarioRevisionChange(BaseModel):
    path: str
    kind: Literal["added", "removed", "modified"]
    breaking: bool = False
    before: Any | None = None
    after: Any | None = None


class ScenarioRevisionComparison(BaseModel):
    simulation_id: str
    scenario_id: str
    from_revision: int
    to_revision: int
    change_count: int
    breaking_change_count: int
    changes: list[ScenarioRevisionChange]


class ScenarioGraphDiagnostic(BaseModel):
    severity: Literal["info", "warning"]
    code: Literal["unreachable-state", "terminal-state", "self-transition"]
    message: str
    state: str
    handler: str | None = None


class ScenarioSummary(BaseModel):
    simulation_id: str
    scenario_id: str
    name: str
    description: str
    initial_state: str
    reset_state: str
    state_count: int
    handler_count: int
    warning_count: int = 0


class ScenarioRuntimeState(BaseModel):
    simulation_id: str
    scenario_id: str
    wiremock_scenario_name: str
    configured_initial_state: str
    configured_reset_state: str
    current_state: str | None
    deployed: bool


class ScenarioCompileResult(BaseModel):
    simulation_id: str
    scenario_id: str
    wiremock_scenario_name: str
    mapping_count: int
    status: Literal["compiled"]


class ScenarioDeployResult(BaseModel):
    simulation_id: str
    scenario_id: str
    wiremock_scenario_name: str
    deployed_mappings: int
    current_state: str
    status: Literal["deployed"]
    release_number: int | None = None
    revision: int | None = None
    etag: str | None = None
    mapping_fingerprint: str | None = None
    deployed_at: datetime | None = None
    deployed_by: str | None = None


class ScenarioRelease(BaseModel):
    simulation_id: str
    scenario_id: str
    release_number: int
    revision: int
    etag: str
    mapping_fingerprint: str
    mapping_count: int
    deployed_at: datetime
    deployed_by: str
    source_release: int | None = None
    status: Literal["deployed"] = "deployed"


class ScenarioReleasePolicy(BaseModel):
    require_approval: bool = False
    block_breaking_changes: bool = False
    updated_at: datetime | None = None
    updated_by: str | None = None


class ScenarioReview(BaseModel):
    simulation_id: str
    scenario_id: str
    review_number: int
    revision: int
    etag: str
    status: Literal["pending", "approved", "rejected"]
    requested_at: datetime
    requested_by: str
    request_note: str = ""
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""


class ScenarioReviewRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class ScenarioReviewDecision(BaseModel):
    note: str = Field(default="", max_length=500)


class ScenarioReleasePolicyUpdate(BaseModel):
    require_approval: bool = False
    block_breaking_changes: bool = False


class ScenarioPromotionRequest(BaseModel):
    target_simulation_id: str
    target_scenario_id: str | None = None
    expected_target_etag: str | None = None


class ScenarioPromotionResult(BaseModel):
    source_simulation_id: str
    source_scenario_id: str
    source_revision: int
    target_simulation_id: str
    target_scenario_id: str
    target_revision: int
    target_etag: str
    promoted_by: str
    status: Literal["promoted"] = "promoted"


class ScenarioTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    definition: ScenarioDefinition
    created_at: datetime
    created_by: str
    source_simulation_id: str
    source_scenario_id: str
    source_revision: int
    parameters: list[str] = Field(default_factory=list)


class ScenarioTemplateCreate(BaseModel):
    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: str = Field(min_length=3, max_length=100)
    description: str = Field(default="", max_length=500)
    parameterize: dict[str, str] = Field(default_factory=dict, max_length=50)


class ScenarioTemplateInstantiate(BaseModel):
    simulation_id: str
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    expected_etag: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict, max_length=50)


class ScenarioResetResult(BaseModel):
    simulation_id: str
    scenario_id: str
    wiremock_scenario_name: str
    current_state: str
    status: Literal["reset"]


class ScenarioResetAllResult(BaseModel):
    reset_scenarios: int
    status: Literal["reset"]


class ScenarioClockAdvance(BaseModel):
    milliseconds: int = Field(ge=1, le=604_800_000)


class ScenarioClockView(BaseModel):
    simulation_id: str
    scenario_id: str
    elapsed_ms: int
    current_state: str
    transitions_applied: list[str] = Field(default_factory=list)


class ScenarioEventPublish(BaseModel):
    topic: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    payload: Any = None


class ScenarioEventResult(BaseModel):
    simulation_id: str
    topic: str
    transitioned_scenarios: dict[str, str] = Field(default_factory=dict)
    event_id: str


class WorkspaceRestoreResult(BaseModel):
    restored_files: int
    restored_bytes: int
    status: Literal["restored"] = "restored"
