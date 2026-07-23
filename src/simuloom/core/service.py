from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from simuloom.core.audit import AuditLog
from simuloom.core.behavior import SUPPORTED_PROFILES, apply_behavior_profile
from simuloom.core.cases import compile_contract_case_mappings, generate_contract_cases
from simuloom.core.compiler import (
    compile_eligibility_dataset_mappings,
    compile_eligibility_journey,
    compile_wiremock_mappings,
)
from simuloom.core.contracts import analyze_contract, is_eligibility_contract
from simuloom.core.data import generate_members
from simuloom.core.edge_cases import compile_edge_case_mappings, generate_edge_cases
from simuloom.core.evidence import (
    EvidenceEngine,
    build_edge_validation_cases,
    build_pairwise_validation_cases,
    build_scenario_validation_cases,
    build_validation_cases,
)
from simuloom.core.manifest import (
    build_manifest,
    dump_manifest,
    read_bundle,
)
from simuloom.core.manifest import (
    export_bundle as create_export_bundle,
)
from simuloom.core.metrics import MetricsRegistry
from simuloom.core.pairwise import compile_pairwise_mappings, generate_pairwise_cases
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.scenario_approvals import ScenarioApprovalError, ScenarioApprovalStore
from simuloom.core.scenario_comparison import compare_scenario_revisions
from simuloom.core.scenario_graph import scenario_graph_diagnostics
from simuloom.core.scenario_releases import ScenarioReleaseStore
from simuloom.core.scenario_revisions import ScenarioRevisionStore
from simuloom.core.scenario_templates import ScenarioTemplateStore
from simuloom.core.scenarios import (
    compile_scenario_mappings,
    validate_scenario_contract,
    wiremock_scenario_name,
)
from simuloom.core.workspace_backup import create_workspace_backup, restore_workspace_backup
from simuloom.models import (
    CompileResult,
    ContractSummary,
    DataGenerationResult,
    DatasetView,
    DeployResult,
    EvidenceReport,
    ExportResult,
    ImportResult,
    OperationSummary,
    ProfileResult,
    ScenarioClockView,
    ScenarioCompileResult,
    ScenarioDefinition,
    ScenarioDeployResult,
    ScenarioEventResult,
    ScenarioGraphDiagnostic,
    ScenarioPromotionResult,
    ScenarioRelease,
    ScenarioReleasePolicy,
    ScenarioResetAllResult,
    ScenarioResetResult,
    ScenarioReview,
    ScenarioRevision,
    ScenarioRevisionComparison,
    ScenarioRevisionSummary,
    ScenarioRuntimeState,
    ScenarioSummary,
    ScenarioTemplate,
    ScenarioView,
    Simulation,
    SimulationSummary,
    ValidationPlan,
    ValidationPlanCase,
    WorkspaceRestoreResult,
)
from simuloom.runtime.base import RuntimeAdapter
from simuloom.runtime.translation import from_wiremock_mappings


class SimulationService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        runtime: RuntimeAdapter,
        metrics: MetricsRegistry | None = None,
    ):
        self.repository = repository
        self.runtime = runtime
        self.wiremock = runtime  # Backward-compatible internal alias for integrations.
        self.revisions = ScenarioRevisionStore(repository)
        self.releases = ScenarioReleaseStore(repository)
        self.approvals = ScenarioApprovalStore(repository)
        self.templates = ScenarioTemplateStore(repository)
        self.domain_audit = AuditLog(repository.root / "audit" / "domain-events.jsonl")
        self.metrics = metrics or MetricsRegistry()

    def analyze(self, contract: dict[str, Any]) -> ContractSummary:
        return analyze_contract(contract)

    def create(self, name: str, contract: dict[str, Any]) -> Simulation:
        summary = self.analyze(contract)
        simulation_id = self.repository.create(name, contract, summary.fingerprint)
        return Simulation(
            id=simulation_id,
            name=name,
            fingerprint=summary.fingerprint,
            status="created",
            operation_count=len(summary.operations),
        )

    def get(self, simulation_id: str) -> dict[str, Any]:
        return self.repository.read_json(simulation_id, "simulation.json")

    def list_simulations(self) -> list[SimulationSummary]:
        simulations: list[SimulationSummary] = []
        for simulation_id in self.repository.simulation_ids():
            metadata = self.repository.read_json(simulation_id, "simulation.json")
            contract = self.repository.read_json(simulation_id, "contract.json")
            summary = self.analyze(contract)
            root = self.repository.path(simulation_id)
            simulations.append(
                SimulationSummary(
                    id=simulation_id,
                    name=metadata["name"],
                    fingerprint=metadata["fingerprint"],
                    status=metadata["status"],
                    operation_count=len(summary.operations),
                    active_profile=metadata.get("activeProfile", "normal"),
                    scenario_count=len(self.repository.read_scenarios(simulation_id)),
                    has_dataset=(root / "datasets" / "metadata.json").is_file(),
                    has_report=(root / "reports" / "latest.json").is_file(),
                )
            )
        return simulations

    def configure_scenario(
        self,
        simulation_id: str,
        scenario_id: str,
        definition: ScenarioDefinition,
        actor: str = "api-client",
        expected_etag: str | None = None,
    ) -> ScenarioView:
        self._require_simulation(simulation_id)
        contract = self.repository.read_json(simulation_id, "contract.json")
        validate_scenario_contract(contract, definition)
        revision = self.revisions.save(
            simulation_id,
            scenario_id,
            definition,
            actor,
            expected_etag,
        )
        self.metrics.increment("scenario_saves_total")
        return ScenarioView(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            definition=definition,
            revision=revision.revision,
            etag=revision.etag,
            updated_at=revision.created_at,
            updated_by=revision.created_by,
        )

    def get_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioView:
        self._require_simulation(simulation_id)
        definition = ScenarioDefinition.model_validate(
            self.repository.read_scenario(simulation_id, scenario_id)
        )
        revision = self.revisions.current(simulation_id, scenario_id, definition)
        return ScenarioView(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            definition=definition,
            revision=revision.revision,
            etag=revision.etag,
            updated_at=revision.created_at,
            updated_by=revision.created_by,
        )

    def scenario_history(
        self, simulation_id: str, scenario_id: str
    ) -> list[ScenarioRevisionSummary]:
        view = self.get_scenario(simulation_id, scenario_id)
        return self.revisions.history(simulation_id, scenario_id, view.definition)

    def scenario_revision(
        self, simulation_id: str, scenario_id: str, revision: int
    ) -> ScenarioRevision:
        self.get_scenario(simulation_id, scenario_id)
        return self.revisions.revision(simulation_id, scenario_id, revision)

    def restore_scenario_revision(
        self,
        simulation_id: str,
        scenario_id: str,
        revision: int,
        actor: str,
        expected_etag: str | None = None,
    ) -> ScenarioView:
        historical = self.scenario_revision(simulation_id, scenario_id, revision)
        return self.configure_scenario(
            simulation_id,
            scenario_id,
            historical.definition,
            actor,
            expected_etag,
        )

    def compare_scenario_revisions(
        self,
        simulation_id: str,
        scenario_id: str,
        from_revision: int,
        to_revision: int,
    ) -> ScenarioRevisionComparison:
        before = self.scenario_revision(simulation_id, scenario_id, from_revision)
        after = self.scenario_revision(simulation_id, scenario_id, to_revision)
        return compare_scenario_revisions(
            simulation_id,
            scenario_id,
            from_revision,
            before.definition,
            to_revision,
            after.definition,
        )

    def scenario_release_policy(self, simulation_id: str) -> ScenarioReleasePolicy:
        self._require_simulation(simulation_id)
        return self.approvals.policy(simulation_id)

    def promote_scenario_revision(
        self,
        source_simulation_id: str,
        source_scenario_id: str,
        source_revision: int,
        target_simulation_id: str,
        target_scenario_id: str | None,
        actor: str,
        expected_target_etag: str | None = None,
    ) -> ScenarioPromotionResult:
        source = self.scenario_revision(source_simulation_id, source_scenario_id, source_revision)
        selected_target_id = target_scenario_id or source_scenario_id
        target = self.configure_scenario(
            target_simulation_id,
            selected_target_id,
            source.definition,
            actor=actor,
            expected_etag=expected_target_etag,
        )
        self._record_domain_event(
            actor,
            "scenario-promoted",
            target_simulation_id,
            selected_target_id,
            f"from-{source_simulation_id}-revision-{source_revision}",
        )
        self.metrics.increment("scenario_promotions_total")
        return ScenarioPromotionResult(
            source_simulation_id=source_simulation_id,
            source_scenario_id=source_scenario_id,
            source_revision=source_revision,
            target_simulation_id=target_simulation_id,
            target_scenario_id=selected_target_id,
            target_revision=target.revision,
            target_etag=target.etag,
            promoted_by=actor,
        )

    def create_scenario_template(
        self,
        simulation_id: str,
        scenario_id: str,
        revision: int,
        template_id: str,
        name: str,
        description: str,
        actor: str,
        parameterize: dict[str, str] | None = None,
    ) -> ScenarioTemplate:
        source = self.scenario_revision(simulation_id, scenario_id, revision)
        template = self.templates.create(
            template_id, name, description, source, actor, parameterize
        )
        self._record_domain_event(
            actor, "template-created", simulation_id, scenario_id, template_id
        )
        return template

    def scenario_templates(self) -> list[ScenarioTemplate]:
        return self.templates.list()

    def get_scenario_template(self, template_id: str) -> ScenarioTemplate:
        return self.templates.get(template_id)

    def instantiate_scenario_template(
        self,
        template_id: str,
        simulation_id: str,
        scenario_id: str,
        actor: str,
        expected_etag: str | None = None,
        parameters: dict[str, str] | None = None,
    ) -> ScenarioView:
        self.templates.get(template_id)
        definition = self.templates.render(template_id, parameters or {})
        view = self.configure_scenario(
            simulation_id,
            scenario_id,
            definition,
            actor,
            expected_etag,
        )
        self._record_domain_event(
            actor, "template-instantiated", simulation_id, scenario_id, template_id
        )
        self.metrics.increment("template_instantiations_total")
        return view

    def update_scenario_release_policy(
        self,
        simulation_id: str,
        require_approval: bool,
        block_breaking_changes: bool,
        actor: str,
    ) -> ScenarioReleasePolicy:
        self._require_simulation(simulation_id)
        policy = self.approvals.update_policy(
            simulation_id, require_approval, block_breaking_changes, actor
        )
        self._record_domain_event(actor, "policy-update", simulation_id)
        return policy

    def request_scenario_review(
        self,
        simulation_id: str,
        scenario_id: str,
        revision: int,
        actor: str,
        note: str = "",
    ) -> ScenarioReview:
        selected = self.scenario_revision(simulation_id, scenario_id, revision)
        review = self.approvals.request(selected, actor, note)
        self._record_domain_event(
            actor,
            "review-request",
            simulation_id,
            scenario_id,
            f"revision-{revision}",
        )
        self.metrics.increment("review_requests_total")
        return review

    def scenario_reviews(self, simulation_id: str, scenario_id: str) -> list[ScenarioReview]:
        self.get_scenario(simulation_id, scenario_id)
        return self.approvals.list(simulation_id, scenario_id)

    def decide_scenario_review(
        self,
        simulation_id: str,
        scenario_id: str,
        review_number: int,
        approved: bool,
        actor: str,
        note: str = "",
    ) -> ScenarioReview:
        self.get_scenario(simulation_id, scenario_id)
        review = self.approvals.decide(
            simulation_id, scenario_id, review_number, approved, actor, note
        )
        self._record_domain_event(
            actor,
            "review-approved" if approved else "review-rejected",
            simulation_id,
            scenario_id,
            f"review-{review_number}",
        )
        self.metrics.increment("review_approvals_total" if approved else "review_rejections_total")
        return review

    def domain_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.domain_audit.read_events(limit)

    def verify_domain_audit(self) -> dict[str, Any]:
        return self.domain_audit.verify()

    def _record_domain_event(
        self,
        actor: str,
        action: str,
        simulation_id: str,
        scenario_id: str | None = None,
        target: str | None = None,
    ) -> None:
        path = "/".join(
            item for item in ["domain", simulation_id, scenario_id, target, action] if item
        )
        self.domain_audit.append(
            request_id=str(uuid.uuid4()),
            subject=actor,
            role="domain",
            key_id=None,
            method="EVENT",
            path=path,
            status_code=200,
            duration_ms=0,
            outcome="recorded",
        )

    def list_scenarios(self, simulation_id: str) -> list[ScenarioSummary]:
        self._require_simulation(simulation_id)
        summaries: list[ScenarioSummary] = []
        for scenario_id, payload in sorted(self.repository.read_scenarios(simulation_id).items()):
            definition = ScenarioDefinition.model_validate(payload)
            diagnostics = scenario_graph_diagnostics(definition)
            summaries.append(
                ScenarioSummary(
                    simulation_id=simulation_id,
                    scenario_id=scenario_id,
                    name=definition.name,
                    description=definition.description,
                    initial_state=definition.initial_state,
                    reset_state=definition.reset_state,
                    state_count=len(definition.states),
                    handler_count=sum(len(state.handlers) for state in definition.states),
                    warning_count=sum(item.severity == "warning" for item in diagnostics),
                )
            )
        return summaries

    def scenario_diagnostics(
        self, simulation_id: str, scenario_id: str
    ) -> list[ScenarioGraphDiagnostic]:
        return scenario_graph_diagnostics(self.get_scenario(simulation_id, scenario_id).definition)

    def contract_operations(self, simulation_id: str) -> list[OperationSummary]:
        contract = self.repository.read_json(simulation_id, "contract.json")
        return self.analyze(contract).operations

    def compile_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioCompileResult:
        view = self.get_scenario(simulation_id, scenario_id)
        contract = self.repository.read_json(simulation_id, "contract.json")
        validate_scenario_contract(contract, view.definition)
        mappings = compile_scenario_mappings(simulation_id, scenario_id, view.definition)
        self.repository.write_json(
            simulation_id, f"mappings/scenarios/{scenario_id}.json", mappings
        )
        return ScenarioCompileResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=wiremock_scenario_name(simulation_id, scenario_id),
            mapping_count=len(mappings),
            status="compiled",
        )

    async def scenario_state(self, simulation_id: str, scenario_id: str) -> ScenarioRuntimeState:
        view = self.get_scenario(simulation_id, scenario_id)
        name = wiremock_scenario_name(simulation_id, scenario_id)
        current = await self.runtime.scenario_state(name)
        configured = view.definition
        releases = self.releases.list(simulation_id, scenario_id)
        if current is not None and releases:
            configured = self.scenario_revision(
                simulation_id, scenario_id, releases[0].revision
            ).definition
        return ScenarioRuntimeState(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=name,
            configured_initial_state=configured.initial_state,
            configured_reset_state=configured.reset_state,
            current_state=current,
            deployed=current is not None,
        )

    async def deploy_scenario(
        self,
        simulation_id: str,
        scenario_id: str,
        actor: str = "api-client",
        revision: int | None = None,
        source_release: int | None = None,
    ) -> ScenarioDeployResult:
        view = self.get_scenario(simulation_id, scenario_id)
        selected = self.scenario_revision(simulation_id, scenario_id, revision or view.revision)
        self._require_scenario_deployable(selected, source_release is not None)
        contract = self.repository.read_json(simulation_id, "contract.json")
        validate_scenario_contract(contract, selected.definition)
        mappings = compile_scenario_mappings(simulation_id, scenario_id, selected.definition)
        self.repository.write_json(
            simulation_id, f"mappings/scenarios/{scenario_id}.json", mappings
        )
        scenario_name = wiremock_scenario_name(simulation_id, scenario_id)
        deployed = await self.runtime.deploy_scenario(
            from_wiremock_mappings(mappings),
            scenario_name,
            selected.definition.initial_state,
            simulation_id,
        )
        release = self.releases.record(selected, mappings, actor, source_release=source_release)
        self.metrics.increment(
            "scenario_rollbacks_total"
            if source_release is not None
            else "scenario_deployments_total"
        )
        return ScenarioDeployResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=scenario_name,
            deployed_mappings=deployed,
            current_state=selected.definition.initial_state,
            status="deployed",
            release_number=release.release_number,
            revision=release.revision,
            etag=release.etag,
            mapping_fingerprint=release.mapping_fingerprint,
            deployed_at=release.deployed_at,
            deployed_by=release.deployed_by,
        )

    def scenario_releases(self, simulation_id: str, scenario_id: str) -> list[ScenarioRelease]:
        self.get_scenario(simulation_id, scenario_id)
        return self.releases.list(simulation_id, scenario_id)

    def scenario_release(
        self, simulation_id: str, scenario_id: str, release_number: int
    ) -> ScenarioRelease:
        self.get_scenario(simulation_id, scenario_id)
        return self.releases.get(simulation_id, scenario_id, release_number)

    async def rollback_scenario_release(
        self,
        simulation_id: str,
        scenario_id: str,
        release_number: int,
        actor: str,
    ) -> ScenarioDeployResult:
        release = self.scenario_release(simulation_id, scenario_id, release_number)
        return await self.deploy_scenario(
            simulation_id,
            scenario_id,
            actor=actor,
            revision=release.revision,
            source_release=release_number,
        )

    async def reset_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioResetResult:
        view = self.get_scenario(simulation_id, scenario_id)
        name = wiremock_scenario_name(simulation_id, scenario_id)
        if await self.runtime.scenario_state(name) is None:
            raise RuntimeError("Deploy this scenario before resetting it")
        definition = view.definition
        releases = self.releases.list(simulation_id, scenario_id)
        if releases:
            definition = self.scenario_revision(
                simulation_id, scenario_id, releases[0].revision
            ).definition
        await self.runtime.set_scenario_state(name, definition.reset_state)
        return ScenarioResetResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=name,
            current_state=definition.reset_state,
            status="reset",
        )

    async def advance_scenario_clock(
        self, simulation_id: str, scenario_id: str, milliseconds: int, actor: str
    ) -> ScenarioClockView:
        view = self.get_scenario(simulation_id, scenario_id)
        runtime = await self.scenario_state(simulation_id, scenario_id)
        if not runtime.deployed or runtime.current_state is None:
            raise RuntimeError("Deploy this scenario before advancing its virtual clock")
        try:
            clock = self.repository.read_json(simulation_id, f"scenarios/clocks/{scenario_id}.json")
        except FileNotFoundError:
            clock = {"state": runtime.current_state, "elapsed_ms": 0}
        if clock.get("state") != runtime.current_state:
            clock = {"state": runtime.current_state, "elapsed_ms": 0}
        elapsed = int(clock.get("elapsed_ms", 0)) + milliseconds
        current = runtime.current_state
        transitions: list[str] = []
        definition = view.definition
        releases = self.releases.list(simulation_id, scenario_id)
        if releases:
            definition = self.scenario_revision(
                simulation_id, scenario_id, releases[0].revision
            ).definition
        states = {state.name: state for state in definition.states}
        while (state := states[current]).timeout_ms and elapsed >= state.timeout_ms:
            elapsed -= state.timeout_ms
            current = state.timeout_state or current
            transitions.append(current)
            if len(transitions) > len(states):
                raise RuntimeError("Virtual clock timeout cycle exceeded one full graph traversal")
        await self.runtime.set_scenario_state(
            wiremock_scenario_name(simulation_id, scenario_id), current
        )
        self.repository.write_json(
            simulation_id,
            f"scenarios/clocks/{scenario_id}.json",
            {"state": current, "elapsed_ms": elapsed},
        )
        self._record_domain_event(actor, "clock-advanced", simulation_id, scenario_id)
        self.metrics.increment("virtual_clock_advances_total")
        return ScenarioClockView(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            elapsed_ms=elapsed,
            current_state=current,
            transitions_applied=transitions,
        )

    async def publish_scenario_event(
        self, simulation_id: str, topic: str, payload: Any, actor: str
    ) -> ScenarioEventResult:
        self._require_simulation(simulation_id)
        if len(json.dumps(payload, separators=(",", ":")).encode()) > 1024 * 1024:
            raise ValueError("Scenario event payload cannot exceed 1 MiB")
        transitioned: dict[str, str] = {}
        event_id = str(uuid.uuid4())
        for scenario_id in self.repository.read_scenarios(simulation_id):
            runtime = await self.scenario_state(simulation_id, scenario_id)
            if not runtime.deployed or runtime.current_state is None:
                continue
            releases = self.releases.list(simulation_id, scenario_id)
            view = self.get_scenario(simulation_id, scenario_id)
            definition = (
                self.scenario_revision(simulation_id, scenario_id, releases[0].revision).definition
                if releases
                else view.definition
            )
            state = next(item for item in definition.states if item.name == runtime.current_state)
            transition = next(
                (item for item in state.event_transitions if item.topic == topic), None
            )
            if transition is None:
                continue
            await self.runtime.set_scenario_state(
                wiremock_scenario_name(simulation_id, scenario_id), transition.new_state
            )
            transitioned[scenario_id] = transition.new_state
        self.repository.write_json(
            simulation_id,
            f"events/{event_id}.json",
            {"event_id": event_id, "topic": topic, "payload": payload, "actor": actor},
        )
        self._record_domain_event(actor, "event-published", simulation_id, target=topic)
        self.metrics.increment("scenario_events_total")
        return ScenarioEventResult(
            simulation_id=simulation_id,
            topic=topic,
            transitioned_scenarios=transitioned,
            event_id=event_id,
        )

    def metrics_snapshot(self) -> dict[str, int]:
        return self.metrics.snapshot()

    def prometheus_metrics(self) -> str:
        return self.metrics.prometheus()

    def workspace_backup(self) -> bytes:
        return create_workspace_backup(self.repository.root)

    def restore_workspace(self, data: bytes, actor: str) -> WorkspaceRestoreResult:
        result = restore_workspace_backup(self.repository.root, data)
        self.domain_audit = AuditLog(self.repository.root / "audit" / "domain-events.jsonl")
        self._record_domain_event(actor, "workspace-restored", "workspace")
        self.metrics.increment("workspace_restores_total")
        return result

    async def reset_all_scenarios(self) -> ScenarioResetAllResult:
        await self.runtime.reset_all_scenarios()
        reset_count = 0
        for simulation_id in self.repository.simulation_ids():
            for scenario_id, payload in self.repository.read_scenarios(simulation_id).items():
                definition = ScenarioDefinition.model_validate(payload)
                releases = self.releases.list(simulation_id, scenario_id)
                if releases:
                    definition = self.scenario_revision(
                        simulation_id, scenario_id, releases[0].revision
                    ).definition
                name = wiremock_scenario_name(simulation_id, scenario_id)
                if await self.runtime.scenario_state(name) is not None:
                    await self.runtime.set_scenario_state(name, definition.reset_state)
                    reset_count += 1
        return ScenarioResetAllResult(reset_scenarios=reset_count, status="reset")

    def generate_data(self, simulation_id: str, records: int, seed: int) -> DataGenerationResult:
        self._require_simulation(simulation_id)
        if not 1 <= records <= 10_000:
            raise ValueError("records must be between 1 and 10000")
        contract = self.repository.read_json(simulation_id, "contract.json")
        if is_eligibility_contract(contract):
            dataset = "members"
            generated = generate_members(records, seed)
            relative_path = "datasets/members.json"
            provider = "synthetic-eligibility"
        else:
            dataset = "contract-cases"
            generated = generate_contract_cases(contract, records, seed)
            relative_path = "datasets/cases.json"
            provider = "openapi-schema"
        self.repository.write_json(simulation_id, relative_path, generated)
        self.repository.write_json(
            simulation_id,
            "datasets/metadata.json",
            {
                "dataset": dataset,
                "provider": provider,
                "path": relative_path,
                "recordCount": records,
                "seed": seed,
                "synthetic": True,
            },
        )
        self.repository.update_status(simulation_id, "data-generated")
        return DataGenerationResult(
            simulation_id=simulation_id,
            dataset=dataset,
            provider=provider,
            record_count=records,
            seed=seed,
        )

    def get_dataset(self, simulation_id: str) -> DatasetView:
        self._require_simulation(simulation_id)
        metadata = self.repository.read_json(simulation_id, "datasets/metadata.json")
        relative_path = metadata.get("path") or (
            "datasets/members.json"
            if metadata.get("dataset") == "members"
            else "datasets/cases.json"
        )
        provider = metadata.get("provider") or (
            "synthetic-eligibility" if metadata.get("dataset") == "members" else "openapi-schema"
        )
        records = self.repository.read_json(simulation_id, relative_path)
        return DatasetView(
            simulation_id=simulation_id,
            dataset=metadata["dataset"],
            provider=provider,
            synthetic=metadata.get("synthetic") is True,
            record_count=len(records),
            seed=int(metadata["seed"]),
            records=records,
        )

    def compile(self, simulation_id: str) -> CompileResult:
        self._require_simulation(simulation_id)
        contract = self.repository.read_json(simulation_id, "contract.json")
        contract_mappings = compile_wiremock_mappings(contract)
        edge_mappings = compile_edge_case_mappings(
            generate_edge_cases(contract, max_per_operation=50)
        )
        pairwise_mappings = compile_pairwise_mappings(
            generate_pairwise_cases(contract, max_per_operation=50)
        )
        dataset_mappings: list[dict[str, Any]] = []
        overridden_operations: set[str] = set()
        try:
            members = self.repository.read_json(simulation_id, "datasets/members.json")
            dataset_mappings, overridden_operations = compile_eligibility_dataset_mappings(
                contract, members
            )
        except FileNotFoundError:
            try:
                cases = self.repository.read_json(simulation_id, "datasets/cases.json")
                dataset_mappings = compile_contract_case_mappings(cases)
            except FileNotFoundError:
                pass

        stateful_mappings, stateful_operations = compile_eligibility_journey(contract)
        overridden_operations.update(stateful_operations)
        configured_scenario_mappings: list[dict[str, Any]] = []
        for scenario_id, payload in self.repository.read_scenarios(simulation_id).items():
            definition = ScenarioDefinition.model_validate(payload)
            validate_scenario_contract(contract, definition)
            configured_scenario_mappings.extend(
                compile_scenario_mappings(simulation_id, scenario_id, definition)
            )

        active_contract_mappings = [
            mapping
            for mapping in contract_mappings
            if mapping.get("metadata", {}).get("simuloomOperationId") not in overridden_operations
        ]
        base_mappings = [
            *dataset_mappings,
            *stateful_mappings,
            *configured_scenario_mappings,
            *edge_mappings,
            *pairwise_mappings,
            *active_contract_mappings,
        ]
        fallback_count = sum(
            1
            for mapping in dataset_mappings
            if mapping.get("metadata", {}).get("simuloomFallback") is True
        )
        profile = self._profile(simulation_id)
        mappings = apply_behavior_profile(
            base_mappings,
            profile=profile["name"],
            simulation_id=simulation_id,
            fixed_delay_ms=profile["fixedDelayMs"],
            failure_status=profile["failureStatus"],
        )
        for mapping in mappings:
            mapping.setdefault("metadata", {})["simuloomSimulationId"] = simulation_id
        self.repository.write_json(simulation_id, "mappings/mappings.json", mappings)
        self.repository.write_json(
            simulation_id,
            "mappings/metadata.json",
            {
                "mappingCount": len(mappings),
                "contractMappingCount": len(active_contract_mappings),
                "datasetMappingCount": len(dataset_mappings) - fallback_count,
                "fallbackMappingCount": fallback_count,
                "statefulMappingCount": len(stateful_mappings) + len(configured_scenario_mappings),
                "edgeMappingCount": len(edge_mappings),
                "pairwiseMappingCount": len(pairwise_mappings),
                "configuredScenarioMappingCount": len(configured_scenario_mappings),
                "activeProfile": profile["name"],
            },
        )
        self.repository.update_status(simulation_id, "compiled")
        return CompileResult(
            simulation_id=simulation_id,
            mapping_count=len(mappings),
            contract_mapping_count=len(active_contract_mappings),
            dataset_mapping_count=len(dataset_mappings) - fallback_count,
            fallback_mapping_count=fallback_count,
            stateful_mapping_count=len(stateful_mappings) + len(configured_scenario_mappings),
            edge_mapping_count=len(edge_mappings),
            pairwise_mapping_count=len(pairwise_mappings),
            active_profile=profile["name"],
            status="compiled",
        )

    def activate_profile(
        self, simulation_id: str, profile: str, fixed_delay_ms: int, failure_status: int
    ) -> ProfileResult:
        self._require_simulation(simulation_id)
        if profile not in SUPPORTED_PROFILES:
            supported = ", ".join(sorted(SUPPORTED_PROFILES))
            raise ValueError(f"Unsupported profile '{profile}'. Choose one of: {supported}")
        if not 0 <= fixed_delay_ms <= 60_000:
            raise ValueError("fixed_delay_ms must be between 0 and 60000")
        if not 500 <= failure_status <= 599:
            raise ValueError("failure_status must be between 500 and 599")
        self.repository.write_json(
            simulation_id,
            "behavior/profile.json",
            {
                "name": profile,
                "fixedDelayMs": fixed_delay_ms,
                "failureStatus": failure_status,
            },
        )
        metadata = self.repository.read_json(simulation_id, "simulation.json")
        metadata["activeProfile"] = profile
        self.repository.write_json(simulation_id, "simulation.json", metadata)
        compiled = self.compile(simulation_id)
        return ProfileResult(
            simulation_id=simulation_id,
            active_profile=profile,
            fixed_delay_ms=fixed_delay_ms,
            failure_status=failure_status,
            mapping_count=compiled.mapping_count,
            status="profile-activated",
        )

    async def deploy(
        self,
        simulation_id: str,
        reset_existing: bool = False,
        actor: str = "api-client",
    ) -> DeployResult:
        self._require_simulation(simulation_id)
        try:
            mappings = self.repository.read_json(simulation_id, "mappings/mappings.json")
        except FileNotFoundError:
            self.compile(simulation_id)
            mappings = self.repository.read_json(simulation_id, "mappings/mappings.json")
        for scenario_id in self.repository.read_scenarios(simulation_id):
            view = self.get_scenario(simulation_id, scenario_id)
            selected = self.scenario_revision(simulation_id, scenario_id, view.revision)
            self._require_scenario_deployable(selected, False)
        deployed = await self.runtime.deploy(
            from_wiremock_mappings(mappings), reset_existing, simulation_id
        )
        for scenario_id, payload in self.repository.read_scenarios(simulation_id).items():
            definition = ScenarioDefinition.model_validate(payload)
            await self.runtime.set_scenario_state(
                wiremock_scenario_name(simulation_id, scenario_id),
                definition.initial_state,
            )
            view = self.get_scenario(simulation_id, scenario_id)
            revision = self.scenario_revision(simulation_id, scenario_id, view.revision)
            scenario_mappings = self.repository.read_json(
                simulation_id, f"mappings/scenarios/{scenario_id}.json"
            )
            self.releases.record(revision, scenario_mappings, actor)
        self.repository.update_status(simulation_id, "deployed")
        return DeployResult(
            simulation_id=simulation_id,
            wiremock_url=self.runtime.base_url,
            deployed_mappings=deployed,
            status="deployed",
        )

    def _require_scenario_deployable(self, selected: ScenarioRevision, rollback: bool) -> None:
        if rollback:
            return
        policy = self.approvals.policy(selected.simulation_id)
        if policy.block_breaking_changes and selected.revision > 1:
            comparison = self.compare_scenario_revisions(
                selected.simulation_id,
                selected.scenario_id,
                selected.revision - 1,
                selected.revision,
            )
            if comparison.breaking_change_count:
                raise ScenarioApprovalError(
                    f"Scenario revision {selected.revision} contains "
                    f"{comparison.breaking_change_count} blocked breaking changes"
                )
        self.approvals.require_deployable(selected)

    async def validate(
        self,
        simulation_id: str,
        max_dataset_cases: int,
        reset_runtime_state: bool,
        include_boundary_cases: bool = False,
        include_negative_cases: bool = False,
        max_edge_cases_per_operation: int = 12,
        include_pairwise_cases: bool = False,
        max_pairwise_cases_per_operation: int = 25,
    ) -> EvidenceReport:
        self._require_simulation(simulation_id)
        if not 1 <= max_edge_cases_per_operation <= 50:
            raise ValueError("max_edge_cases_per_operation must be between 1 and 50")
        if not 1 <= max_pairwise_cases_per_operation <= 50:
            raise ValueError("max_pairwise_cases_per_operation must be between 1 and 50")
        metadata = self.repository.read_json(simulation_id, "simulation.json")
        if metadata.get("status") not in {"deployed", "validated"}:
            raise RuntimeError("Deploy this simulation before running live validation")
        engine = EvidenceEngine(self.repository, self.runtime)
        report = await engine.run(
            simulation_id,
            max_dataset_cases,
            reset_runtime_state,
            include_boundary_cases,
            include_negative_cases,
            max_edge_cases_per_operation,
            include_pairwise_cases,
            max_pairwise_cases_per_operation,
        )
        self.repository.update_status(simulation_id, "validated")
        return report

    def plan_validation(
        self,
        simulation_id: str,
        max_dataset_cases: int,
        include_boundary_cases: bool = False,
        include_negative_cases: bool = False,
        max_edge_cases_per_operation: int = 12,
        include_pairwise_cases: bool = False,
        max_pairwise_cases_per_operation: int = 25,
    ) -> ValidationPlan:
        self._require_simulation(simulation_id)
        if not 1 <= max_dataset_cases <= 25:
            raise ValueError("max_dataset_cases must be between 1 and 25")
        if not 1 <= max_edge_cases_per_operation <= 50:
            raise ValueError("max_edge_cases_per_operation must be between 1 and 50")
        if not 1 <= max_pairwise_cases_per_operation <= 50:
            raise ValueError("max_pairwise_cases_per_operation must be between 1 and 50")
        contract = self.repository.read_json(simulation_id, "contract.json")
        try:
            members = self.repository.read_json(simulation_id, "datasets/members.json")
        except FileNotFoundError:
            members = []
        try:
            contract_cases = self.repository.read_json(simulation_id, "datasets/cases.json")
        except FileNotFoundError:
            contract_cases = []
        profile = self._profile(simulation_id)
        cases = build_validation_cases(
            contract, members, profile, max_dataset_cases, contract_cases
        )
        cases.extend(
            build_scenario_validation_cases(contract, self.repository.read_scenarios(simulation_id))
        )
        if include_pairwise_cases:
            cases.extend(
                build_pairwise_validation_cases(
                    contract, max_per_operation=max_pairwise_cases_per_operation
                )
            )
        cases.extend(
            build_edge_validation_cases(
                contract,
                include_boundary=include_boundary_cases,
                include_negative=include_negative_cases,
                max_per_operation=max_edge_cases_per_operation,
            )
        )
        planned = [
            ValidationPlanCase(
                name=case.name,
                category=case.category,
                operation_id=case.operation_id,
                method=case.method,
                path=case.path,
                expected_status=case.expected_status,
                headers=case.headers,
                body=case.body,
                validates_response_schema=case.response_schema is not None,
                scenario_id=case.scenario_id,
                scenario_handler=case.scenario_handler,
                required_state=case.required_state,
                new_state=case.new_state,
                reset_before=case.reset_before,
                edge_polarity=case.edge_polarity,
                edge_constraint=case.edge_constraint,
                edge_location=case.edge_location,
                edge_field=case.edge_field,
                pairwise_assignments=case.pairwise_assignments,
                pairwise_pair_ids=case.pairwise_pair_ids or [],
                pairwise_total_pairs=case.pairwise_total_pairs,
            )
            for case in cases
        ]
        return ValidationPlan(
            simulation_id=simulation_id,
            active_profile=profile["name"],
            case_count=len(planned),
            cases=planned,
        )

    def latest_report(self, simulation_id: str) -> EvidenceReport:
        self._require_simulation(simulation_id)
        payload = self.repository.read_json(simulation_id, "reports/latest.json")
        return EvidenceReport.model_validate(payload)

    def latest_report_html(self, simulation_id: str) -> str:
        self._require_simulation(simulation_id)
        return self.repository.read_text(simulation_id, "reports/latest.html")

    def export_bundle(self, simulation_id: str) -> ExportResult:
        self._require_simulation(simulation_id)
        result, _ = create_export_bundle(self.repository, simulation_id)
        return result

    def export_bundle_path(self, simulation_id: str) -> Path:
        self._require_simulation(simulation_id)
        result, path = create_export_bundle(self.repository, simulation_id)
        if result.bundle_name != path.name:
            raise RuntimeError("Export bundle name mismatch")
        return path

    def portable_manifest(self, simulation_id: str) -> str:
        self._require_simulation(simulation_id)
        return dump_manifest(build_manifest(self.repository, simulation_id))

    def import_bundle(self, data: bytes, source_name: str) -> ImportResult:
        contents = read_bundle(data)
        name = str(contents.manifest["metadata"]["name"])
        simulation = self.create(name, contents.contract)
        if contents.dataset_records and contents.dataset_path:
            data_spec = contents.manifest["spec"]["data"]
            provider = data_spec["provider"]
            dataset_name = "members" if provider == "synthetic-eligibility" else "contract-cases"
            self.repository.write_json(
                simulation.id, contents.dataset_path, contents.dataset_records
            )
            self.repository.write_json(
                simulation.id,
                "datasets/metadata.json",
                {
                    "dataset": dataset_name,
                    "provider": provider,
                    "path": contents.dataset_path,
                    "recordCount": len(contents.dataset_records),
                    "seed": int(data_spec["seed"]),
                    "synthetic": True,
                },
            )
        if contents.scenarios:
            self.repository.write_json(
                simulation.id, "scenarios/scenarios.json", contents.scenarios
            )
        profile = contents.profile
        self.repository.write_json(simulation.id, "behavior/profile.json", profile)
        metadata = self.repository.read_json(simulation.id, "simulation.json")
        metadata["activeProfile"] = profile["name"]
        self.repository.write_json(simulation.id, "simulation.json", metadata)
        self.compile(simulation.id)
        simulation = simulation.model_copy(update={"status": "compiled"})
        warnings = []
        if contents.manifest.get("spec", {}).get("data") is None:
            warnings.append("Bundle contains no synthetic dataset")
        warnings.append("Compiled mappings were regenerated from approved source artifacts")
        return ImportResult(
            simulation=simulation,
            manifest_version=contents.manifest["apiVersion"],
            source_name=source_name,
            imported_dataset_records=len(contents.dataset_records),
            active_profile=profile["name"],
            warnings=warnings,
        )

    def _require_simulation(self, simulation_id: str) -> None:
        if not self.repository.exists(simulation_id):
            raise KeyError(f"Simulation not found: {simulation_id}")

    def _profile(self, simulation_id: str) -> dict[str, Any]:
        try:
            return self.repository.read_json(simulation_id, "behavior/profile.json")
        except FileNotFoundError:
            return {"name": "normal", "fixedDelayMs": 2_000, "failureStatus": 503}
