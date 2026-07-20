from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from simuloom.core.cases import validate_contract_cases
from simuloom.core.contracts import contract_fingerprint
from simuloom.core.data import validate_members
from simuloom.core.repository import WorkspaceRepository
from simuloom.models import ExportResult

MANIFEST_VERSION = "simuloom.io/v1alpha1"
ALLOWED_BUNDLE_FILES = {
    "simulation.yaml",
    "contract.json",
    "datasets/members.json",
    "datasets/cases.json",
    "datasets/metadata.json",
    "behavior/profile.json",
    "mappings/mappings.json",
    "mappings/metadata.json",
}
MAX_BUNDLE_SIZE = 20 * 1024 * 1024
MAX_ENTRY_SIZE = 10 * 1024 * 1024


@dataclass(slots=True)
class BundleContents:
    manifest: dict[str, Any]
    contract: dict[str, Any]
    dataset_records: list[dict[str, Any]]
    dataset_path: str | None
    dataset_metadata: dict[str, Any]
    profile: dict[str, Any]


def dataset_fingerprint(records: list[dict[str, Any]]) -> str:
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def build_manifest(repository: WorkspaceRepository, simulation_id: str) -> dict[str, Any]:
    simulation = repository.read_json(simulation_id, "simulation.json")
    contract = repository.read_json(simulation_id, "contract.json")
    try:
        dataset = repository.read_json(simulation_id, "datasets/metadata.json")
    except FileNotFoundError:
        dataset = None
    try:
        profile = repository.read_json(simulation_id, "behavior/profile.json")
    except FileNotFoundError:
        profile = {"name": "normal", "fixedDelayMs": 2_000, "failureStatus": 503}

    spec: dict[str, Any] = {
        "contract": {
            "path": "contract.json",
            "fingerprint": contract_fingerprint(contract),
        },
        "behavior": {"profile": profile},
        "validation": {"maxDatasetCases": 3, "resetRuntimeState": True},
    }
    if dataset is not None:
        dataset_name = dataset.get("dataset", "members")
        dataset_path = dataset.get("path") or (
            "datasets/members.json" if dataset_name == "members" else "datasets/cases.json"
        )
        provider = dataset.get("provider") or (
            "synthetic-eligibility" if dataset_name == "members" else "openapi-schema"
        )
        records = repository.read_json(simulation_id, dataset_path)
        spec["data"] = {
            "provider": provider,
            "path": dataset_path,
            "records": dataset["recordCount"],
            "seed": dataset["seed"],
            "classification": "SYNTHETIC_ONLY",
            "fingerprint": dataset_fingerprint(records),
        }
    return {
        "apiVersion": MANIFEST_VERSION,
        "kind": "Simulation",
        "metadata": {
            "name": simulation["name"],
            "annotations": {
                "simuloom.io/source-simulation-id": simulation_id,
                "simuloom.io/contract-fingerprint": simulation["fingerprint"],
            },
        },
        "spec": spec,
    }


def dump_manifest(manifest: dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)


def _manifest_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Manifest {field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Manifest {field} must be an integer") from exc


def validate_manifest(manifest: dict[str, Any], contract: dict[str, Any]) -> None:
    if manifest.get("apiVersion") != MANIFEST_VERSION:
        raise ValueError(f"Unsupported manifest apiVersion; expected {MANIFEST_VERSION}")
    if manifest.get("kind") != "Simulation":
        raise ValueError("Manifest kind must be Simulation")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict) or not str(metadata.get("name", "")).strip():
        raise ValueError("Manifest metadata.name is required")
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        raise ValueError("Manifest spec is required")
    contract_spec = spec.get("contract")
    if not isinstance(contract_spec, dict):
        raise ValueError("Manifest spec.contract is required")
    if contract_spec.get("path") != "contract.json":
        raise ValueError("Manifest contract path must be contract.json")
    expected = contract_spec.get("fingerprint")
    actual = contract_fingerprint(contract)
    if expected != actual:
        raise ValueError(
            f"Contract fingerprint mismatch: manifest expects {expected}, bundle contains {actual}"
        )
    behavior = spec.get("behavior") or {}
    if not isinstance(behavior, dict):
        raise ValueError("Manifest spec.behavior must be an object")
    profile = behavior.get("profile") or {}
    if not isinstance(profile, dict):
        raise ValueError("Manifest behavior profile must be an object")
    if profile.get("name", "normal") not in {
        "normal",
        "slow",
        "unavailable",
        "intermittent",
    }:
        raise ValueError("Manifest contains an unsupported behavior profile")
    fixed_delay = _manifest_integer(profile.get("fixedDelayMs", 2_000), "fixedDelayMs")
    failure_status = _manifest_integer(profile.get("failureStatus", 503), "failureStatus")
    if not 0 <= fixed_delay <= 60_000:
        raise ValueError("Manifest fixedDelayMs must be between 0 and 60000")
    if not 500 <= failure_status <= 599:
        raise ValueError("Manifest failureStatus must be between 500 and 599")


def export_bundle(repository: WorkspaceRepository, simulation_id: str) -> tuple[ExportResult, Path]:
    manifest = build_manifest(repository, simulation_id)
    manifest_yaml = dump_manifest(manifest)
    repository.write_text(simulation_id, "exports/simulation.yaml", manifest_yaml)
    artifacts: dict[str, bytes] = {
        "simulation.yaml": manifest_yaml.encode(),
        "contract.json": (
            json.dumps(repository.read_json(simulation_id, "contract.json"), indent=2) + "\n"
        ).encode(),
    }
    for relative in sorted(ALLOWED_BUNDLE_FILES - {"simulation.yaml", "contract.json"}):
        source = repository.path(simulation_id) / relative
        if source.is_file():
            artifacts[relative] = source.read_bytes()

    bundle_name = f"{simulation_id}.simuloom.zip"
    bundle_path = repository.path(simulation_id) / "exports" / bundle_name
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(artifacts):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, artifacts[name])
    return (
        ExportResult(
            simulation_id=simulation_id,
            bundle_name=bundle_name,
            manifest_version=MANIFEST_VERSION,
            included_artifacts=sorted(artifacts),
            manifest_yaml=manifest_yaml,
        ),
        bundle_path,
    )


def read_bundle(data: bytes) -> BundleContents:
    if len(data) > MAX_BUNDLE_SIZE:
        raise ValueError("Simulation bundle exceeds the 20 MiB limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP bundle") from exc
    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Simulation bundle contains duplicate artifact paths")
        if len(names) > len(ALLOWED_BUNDLE_FILES):
            raise ValueError("Simulation bundle contains too many files")
        expanded_size = 0
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe bundle path: {info.filename}")
            if info.filename not in ALLOWED_BUNDLE_FILES:
                raise ValueError(f"Unexpected bundle artifact: {info.filename}")
            if info.file_size > MAX_ENTRY_SIZE:
                raise ValueError(f"Bundle artifact is too large: {info.filename}")
            expanded_size += info.file_size
        if expanded_size > MAX_BUNDLE_SIZE:
            raise ValueError("Expanded simulation bundle exceeds the 20 MiB limit")
        if "simulation.yaml" not in names or "contract.json" not in names:
            raise ValueError("Bundle must contain simulation.yaml and contract.json")
        try:
            manifest = yaml.safe_load(archive.read("simulation.yaml"))
            contract = json.loads(archive.read("contract.json"))
        except (json.JSONDecodeError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError("Bundle manifest or contract could not be parsed") from exc
        if not isinstance(manifest, dict) or not isinstance(contract, dict):
            raise ValueError("Manifest and contract must be objects")
        validate_manifest(manifest, contract)
        data_spec = (manifest.get("spec") or {}).get("data")
        dataset_path: str | None = None
        dataset_records: list[dict[str, Any]] = []
        dataset_artifacts = {
            "datasets/members.json",
            "datasets/cases.json",
            "datasets/metadata.json",
        } & set(names)
        if data_spec is not None:
            if not isinstance(data_spec, dict):
                raise ValueError("Manifest spec.data must be an object")
            provider_paths = {
                "synthetic-eligibility": "datasets/members.json",
                "openapi-schema": "datasets/cases.json",
            }
            provider = data_spec.get("provider")
            dataset_path = provider_paths.get(provider)
            if dataset_path is None:
                raise ValueError("Manifest contains an unsupported data provider")
            if data_spec.get("path") != dataset_path:
                raise ValueError(f"Manifest dataset path must be {dataset_path}")
            if dataset_path not in names:
                raise ValueError("Manifest declares a dataset that is missing from the bundle")
            expected_artifacts = {dataset_path, "datasets/metadata.json"}
            if dataset_artifacts != expected_artifacts:
                raise ValueError("Bundle dataset artifacts do not match the manifest")
            dataset_records = json.loads(archive.read(dataset_path))
        elif dataset_artifacts:
            raise ValueError("Bundle dataset is not declared in the manifest")
        dataset_metadata = (
            json.loads(archive.read("datasets/metadata.json"))
            if "datasets/metadata.json" in names
            else {}
        )
        stored_profile = (
            json.loads(archive.read("behavior/profile.json"))
            if "behavior/profile.json" in names
            else {"name": "normal", "fixedDelayMs": 2_000, "failureStatus": 503}
        )
        if not isinstance(dataset_records, list) or any(
            not isinstance(record, dict) or record.get("synthetic") is not True
            for record in dataset_records
        ):
            raise ValueError("Imported datasets must contain synthetic records only")
        if data_spec is not None:
            if data_spec.get("classification") != "SYNTHETIC_ONLY":
                raise ValueError("Bundle dataset must be classified as SYNTHETIC_ONLY")
            record_count = _manifest_integer(data_spec.get("records"), "data.records")
            seed = _manifest_integer(data_spec.get("seed"), "data.seed")
            if record_count < 1:
                raise ValueError("Bundle dataset must contain at least one record")
            if record_count != len(dataset_records):
                raise ValueError("Bundle dataset record count does not match the manifest")
            if data_spec.get("fingerprint") != dataset_fingerprint(dataset_records):
                raise ValueError("Bundle dataset fingerprint mismatch")
            if not isinstance(dataset_metadata, dict):
                raise ValueError("Bundle dataset metadata must be an object")
            if dataset_metadata.get("synthetic") is not True:
                raise ValueError("Bundle dataset metadata must declare synthetic data")
            metadata_count = _manifest_integer(
                dataset_metadata.get("recordCount"), "dataset metadata recordCount"
            )
            metadata_seed = _manifest_integer(dataset_metadata.get("seed"), "dataset metadata seed")
            if metadata_count != len(dataset_records):
                raise ValueError("Bundle dataset metadata record count mismatch")
            if metadata_seed != seed:
                raise ValueError("Bundle dataset seed does not match the manifest")
            if data_spec["provider"] == "synthetic-eligibility":
                validate_members(dataset_records)
            else:
                validate_contract_cases(contract, dataset_records)
        manifest_profile = ((manifest.get("spec") or {}).get("behavior") or {}).get("profile") or {
            "name": "normal",
            "fixedDelayMs": 2_000,
            "failureStatus": 503,
        }
        if stored_profile != manifest_profile:
            raise ValueError("Behavior profile artifact does not match the manifest")
        return BundleContents(
            manifest,
            contract,
            dataset_records,
            dataset_path,
            dataset_metadata,
            manifest_profile,
        )
