from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from simuloom.core.repository import WorkspaceRepository

GITOPS_SCHEMA = "simuloom.io/gitops/v1"


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_snapshot(repository: WorkspaceRepository, simulation_id: str) -> dict[str, Any]:
    metadata = repository.read_json(simulation_id, "simulation.json")
    scenarios = repository.read_scenarios(simulation_id)
    entries = [
        {
            "id": scenario_id,
            "definitionHash": canonical_hash(definition),
        }
        for scenario_id, definition in sorted(scenarios.items())
    ]
    snapshot = {
        "apiVersion": GITOPS_SCHEMA,
        "kind": "SimulationSnapshot",
        "metadata": {"id": simulation_id, "name": metadata["name"]},
        "spec": {
            "contractFingerprint": metadata["fingerprint"],
            "activeProfile": metadata.get("activeProfile", "normal"),
            "scenarios": entries,
        },
    }
    snapshot["integrity"] = canonical_hash(snapshot)
    return snapshot


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("apiVersion") != GITOPS_SCHEMA:
        raise ValueError(f"apiVersion must be {GITOPS_SCHEMA}")
    if snapshot.get("kind") != "SimulationSnapshot":
        raise ValueError("kind must be SimulationSnapshot")
    expected = snapshot.get("integrity")
    unsigned = {key: value for key, value in snapshot.items() if key != "integrity"}
    if not isinstance(expected, str) or expected != canonical_hash(unsigned):
        raise ValueError("GitOps snapshot integrity does not match its content")
    scenarios = snapshot.get("spec", {}).get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("spec.scenarios must be an array")
    ids = [item.get("id") for item in scenarios if isinstance(item, dict)]
    if len(ids) != len(scenarios) or len(set(ids)) != len(ids):
        raise ValueError("Scenario IDs must be present and unique")


def read_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read GitOps snapshot: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("GitOps snapshot must be an object")
    validate_snapshot(payload)
    return payload
