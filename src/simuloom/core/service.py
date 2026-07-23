from __future__ import annotations

from pathlib import Path
from typing import Any

from simuloom.adapters.wiremock import WireMockClient
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
from simuloom.core.pairwise import compile_pairwise_mappings, generate_pairwise_cases
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.scenarios import (
    compile_scenario_mappings,
    validate_scenario_contract,
    wiremock_scenario_name,
)
from simuloom.models import (
    CompileResult,
    ContractSummary,
    DataGenerationResult,
    DatasetView,
    DeployResult,
    EvidenceReport,
    ExportResult,
    ImportResult,
    ProfileResult,
    ScenarioCompileResult,
    ScenarioDefinition,
    ScenarioDeployResult,
    ScenarioResetAllResult,
    ScenarioResetResult,
    ScenarioRuntimeState,
    ScenarioView,
    Simulation,
    ValidationPlan,
    ValidationPlanCase,
)


class SimulationService:
    def __init__(self, repository: WorkspaceRepository, wiremock: WireMockClient):
        self.repository = repository
        self.wiremock = wiremock

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

    def configure_scenario(
        self, simulation_id: str, scenario_id: str, definition: ScenarioDefinition
    ) -> ScenarioView:
        self._require_simulation(simulation_id)
        contract = self.repository.read_json(simulation_id, "contract.json")
        validate_scenario_contract(contract, definition)
        self.repository.write_scenario(
            simulation_id, scenario_id, definition.model_dump(mode="json")
        )
        return ScenarioView(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            definition=definition,
        )

    def get_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioView:
        self._require_simulation(simulation_id)
        definition = ScenarioDefinition.model_validate(
            self.repository.read_scenario(simulation_id, scenario_id)
        )
        return ScenarioView(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            definition=definition,
        )

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
        current = await self.wiremock.scenario_state(name)
        return ScenarioRuntimeState(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=name,
            configured_initial_state=view.definition.initial_state,
            configured_reset_state=view.definition.reset_state,
            current_state=current,
            deployed=current is not None,
        )

    async def deploy_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioDeployResult:
        view = self.get_scenario(simulation_id, scenario_id)
        compiled = self.compile_scenario(simulation_id, scenario_id)
        mappings = self.repository.read_json(
            simulation_id, f"mappings/scenarios/{scenario_id}.json"
        )
        deployed = await self.wiremock.deploy_scenario(
            mappings, compiled.wiremock_scenario_name, view.definition.initial_state
        )
        return ScenarioDeployResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=compiled.wiremock_scenario_name,
            deployed_mappings=deployed,
            current_state=view.definition.initial_state,
            status="deployed",
        )

    async def reset_scenario(self, simulation_id: str, scenario_id: str) -> ScenarioResetResult:
        view = self.get_scenario(simulation_id, scenario_id)
        name = wiremock_scenario_name(simulation_id, scenario_id)
        if await self.wiremock.scenario_state(name) is None:
            raise RuntimeError("Deploy this scenario before resetting it")
        await self.wiremock.set_scenario_state(name, view.definition.reset_state)
        return ScenarioResetResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            wiremock_scenario_name=name,
            current_state=view.definition.reset_state,
            status="reset",
        )

    async def reset_all_scenarios(self) -> ScenarioResetAllResult:
        await self.wiremock.reset_all_scenarios()
        reset_count = 0
        for simulation_id in self.repository.simulation_ids():
            for scenario_id, payload in self.repository.read_scenarios(simulation_id).items():
                definition = ScenarioDefinition.model_validate(payload)
                name = wiremock_scenario_name(simulation_id, scenario_id)
                if await self.wiremock.scenario_state(name) is not None:
                    await self.wiremock.set_scenario_state(name, definition.reset_state)
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

    async def deploy(self, simulation_id: str, reset_existing: bool = False) -> DeployResult:
        self._require_simulation(simulation_id)
        try:
            mappings = self.repository.read_json(simulation_id, "mappings/mappings.json")
        except FileNotFoundError:
            self.compile(simulation_id)
            mappings = self.repository.read_json(simulation_id, "mappings/mappings.json")
        deployed = await self.wiremock.deploy(mappings, reset_existing)
        for scenario_id, payload in self.repository.read_scenarios(simulation_id).items():
            definition = ScenarioDefinition.model_validate(payload)
            await self.wiremock.set_scenario_state(
                wiremock_scenario_name(simulation_id, scenario_id),
                definition.initial_state,
            )
        self.repository.update_status(simulation_id, "deployed")
        return DeployResult(
            simulation_id=simulation_id,
            wiremock_url=self.wiremock.base_url,
            deployed_mappings=deployed,
            status="deployed",
        )

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
        engine = EvidenceEngine(self.repository, self.wiremock)
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
