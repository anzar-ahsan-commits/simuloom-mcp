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
from simuloom.core.evidence import EvidenceEngine, build_validation_cases
from simuloom.core.manifest import (
    build_manifest,
    dump_manifest,
    read_bundle,
)
from simuloom.core.manifest import (
    export_bundle as create_export_bundle,
)
from simuloom.core.repository import WorkspaceRepository
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

        active_contract_mappings = [
            mapping
            for mapping in contract_mappings
            if mapping.get("metadata", {}).get("simuloomOperationId") not in overridden_operations
        ]
        base_mappings = [*dataset_mappings, *stateful_mappings, *active_contract_mappings]
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
                "statefulMappingCount": len(stateful_mappings),
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
            stateful_mapping_count=len(stateful_mappings),
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
        self.repository.update_status(simulation_id, "deployed")
        return DeployResult(
            simulation_id=simulation_id,
            wiremock_url=self.wiremock.base_url,
            deployed_mappings=deployed,
            status="deployed",
        )

    async def validate(
        self, simulation_id: str, max_dataset_cases: int, reset_runtime_state: bool
    ) -> EvidenceReport:
        self._require_simulation(simulation_id)
        metadata = self.repository.read_json(simulation_id, "simulation.json")
        if metadata.get("status") not in {"deployed", "validated"}:
            raise RuntimeError("Deploy this simulation before running live validation")
        engine = EvidenceEngine(self.repository, self.wiremock)
        report = await engine.run(simulation_id, max_dataset_cases, reset_runtime_state)
        self.repository.update_status(simulation_id, "validated")
        return report

    def plan_validation(self, simulation_id: str, max_dataset_cases: int) -> ValidationPlan:
        self._require_simulation(simulation_id)
        if not 1 <= max_dataset_cases <= 25:
            raise ValueError("max_dataset_cases must be between 1 and 25")
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
