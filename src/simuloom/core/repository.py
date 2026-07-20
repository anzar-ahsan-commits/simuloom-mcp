from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any


class WorkspaceRepository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

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
        path = self.path(simulation_id) / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, simulation_id: str, relative_path: str, value: Any) -> None:
        path = self.path(simulation_id) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def write_text(self, simulation_id: str, relative_path: str, value: str) -> None:
        path = self.path(simulation_id) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def read_text(self, simulation_id: str, relative_path: str) -> str:
        path = self.path(simulation_id) / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")
        return path.read_text(encoding="utf-8")

    def update_status(self, simulation_id: str, status: str) -> None:
        metadata = self.read_json(simulation_id, "simulation.json")
        metadata["status"] = status
        self.write_json(simulation_id, "simulation.json", metadata)
