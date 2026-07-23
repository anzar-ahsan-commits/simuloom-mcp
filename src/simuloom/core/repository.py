from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from simuloom.core.locking import exclusive_file_lock

WORKSPACE_FORMAT = "simuloom-workspace"
WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_METADATA_FILE = ".simuloom-workspace.json"


class WorkspaceRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._transaction_state = threading.local()
        self._lock_path = self.root / ".workspace.lock"
        self._lock_path.touch(exist_ok=True)
        self._initialize_workspace()

    @contextmanager
    def transaction(self):
        """Serialize workspace mutations across threads and local worker processes."""
        with self._thread_lock:
            depth = getattr(self._transaction_state, "depth", 0)
            if depth:
                self._transaction_state.depth = depth + 1
                try:
                    yield
                finally:
                    self._transaction_state.depth -= 1
                return
            with exclusive_file_lock(self._lock_path):
                self._transaction_state.depth = 1
                try:
                    yield
                finally:
                    self._transaction_state.depth = 0

    def create(self, name: str, contract: dict[str, Any], fingerprint: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        simulation_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        directory = self.path(simulation_id)
        (directory / "mappings").mkdir(parents=True)
        (directory / "datasets").mkdir()
        (directory / "behavior").mkdir()
        (directory / "reports").mkdir()
        (directory / "exports").mkdir()
        self.write_json(simulation_id, "contract.json", contract)
        (directory / "scenarios").mkdir()
        self.write_json(
            simulation_id,
            "simulation.json",
            {
                "id": simulation_id,
                "name": name,
                "fingerprint": fingerprint,
                "status": "created",
                "activeProfile": "normal",
            },
        )
        self.write_json(
            simulation_id,
            "behavior/profile.json",
            {"name": "normal", "fixedDelayMs": 2_000, "failureStatus": 503},
        )
        return simulation_id

    def path(self, simulation_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]+", simulation_id):
            raise ValueError("Invalid simulation id")
        return self.root / simulation_id

    def exists(self, simulation_id: str) -> bool:
        return (self.path(simulation_id) / "simulation.json").exists()

    def read_json(self, simulation_id: str, relative_path: str) -> Any:
        path = self._artifact_path(simulation_id, relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, simulation_id: str, relative_path: str, value: Any) -> None:
        self._atomic_write(
            self._artifact_path(simulation_id, relative_path),
            json.dumps(value, indent=2) + "\n",
        )

    def write_text(self, simulation_id: str, relative_path: str, value: str) -> None:
        self._atomic_write(self._artifact_path(simulation_id, relative_path), value)

    def read_text(self, simulation_id: str, relative_path: str) -> str:
        path = self._artifact_path(simulation_id, relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def validate_scenario_id(scenario_id: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", scenario_id):
            raise ValueError("Invalid scenario id")

    def read_scenarios(self, simulation_id: str) -> dict[str, Any]:
        if not self.exists(simulation_id):
            raise KeyError(f"Simulation not found: {simulation_id}")
        try:
            payload = self.read_json(simulation_id, "scenarios/scenarios.json")
        except FileNotFoundError:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("Stored scenario collection must be an object")
        return payload

    def read_scenario(self, simulation_id: str, scenario_id: str) -> dict[str, Any]:
        self.validate_scenario_id(scenario_id)
        scenarios = self.read_scenarios(simulation_id)
        if scenario_id not in scenarios:
            raise KeyError(f"Scenario not found: {scenario_id}")
        return scenarios[scenario_id]

    def write_scenario(
        self, simulation_id: str, scenario_id: str, definition: dict[str, Any]
    ) -> None:
        self.validate_scenario_id(scenario_id)
        with self.transaction():
            scenarios = self.read_scenarios(simulation_id)
            scenarios[scenario_id] = definition
            self.write_json(simulation_id, "scenarios/scenarios.json", scenarios)

    def simulation_ids(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and (path / "simulation.json").is_file()
        )

    def diagnostics(self) -> dict[str, Any]:
        metadata = json.loads((self.root / WORKSPACE_METADATA_FILE).read_text(encoding="utf-8"))
        return {
            "format": metadata["format"],
            "schema_version": metadata["schemaVersion"],
            "supported_schema_version": WORKSPACE_SCHEMA_VERSION,
            "writable": os.access(self.root, os.W_OK),
            "simulation_count": len(self.simulation_ids()),
        }

    def update_status(self, simulation_id: str, status: str) -> None:
        with self.transaction():
            metadata = self.read_json(simulation_id, "simulation.json")
            metadata["status"] = status
            self.write_json(simulation_id, "simulation.json", metadata)

    def _artifact_path(self, simulation_id: str, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise ValueError("Artifact path must be relative")
        simulation_root = self.path(simulation_id).resolve()
        path = (simulation_root / relative_path).resolve()
        if not path.is_relative_to(simulation_root):
            raise ValueError("Artifact path escapes the simulation workspace")
        return path

    def _initialize_workspace(self) -> None:
        metadata_path = self.root / WORKSPACE_METADATA_FILE
        if not metadata_path.exists():
            self._atomic_write(
                metadata_path,
                json.dumps(
                    {
                        "format": WORKSPACE_FORMAT,
                        "schemaVersion": WORKSPACE_SCHEMA_VERSION,
                    },
                    indent=2,
                )
                + "\n",
            )
            return
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError("Workspace metadata is unreadable") from exc
        if metadata.get("format") != WORKSPACE_FORMAT:
            raise RuntimeError("Workspace metadata has an unsupported format")
        version = metadata.get("schemaVersion")
        if not isinstance(version, int) or version < 1:
            raise RuntimeError("Workspace metadata has an invalid schema version")
        if version > WORKSPACE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Workspace schema version {version} is newer than supported version "
                f"{WORKSPACE_SCHEMA_VERSION}"
            )

    def _atomic_write(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction():
            descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, path)
                directory_descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            finally:
                temporary_path.unlink(missing_ok=True)
