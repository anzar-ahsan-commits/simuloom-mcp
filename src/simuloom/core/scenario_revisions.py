from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from simuloom.core.repository import WorkspaceRepository
from simuloom.models import ScenarioDefinition, ScenarioRevision, ScenarioRevisionSummary


class ScenarioConflictError(RuntimeError):
    def __init__(self, expected_etag: str, current_etag: str, current_revision: int):
        super().__init__("Scenario was modified by another editor")
        self.expected_etag = expected_etag
        self.current_etag = current_etag
        self.current_revision = current_revision


@dataclass(frozen=True, slots=True)
class RevisionMetadata:
    revision: int
    etag: str
    created_at: datetime
    created_by: str


def definition_etag(definition: ScenarioDefinition) -> str:
    canonical = json.dumps(
        definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


class ScenarioRevisionStore:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository
        self._lock = RLock()

    def current(
        self, simulation_id: str, scenario_id: str, definition: ScenarioDefinition
    ) -> RevisionMetadata:
        with self._lock:
            return self._current(simulation_id, scenario_id, definition)

    def _current(
        self, simulation_id: str, scenario_id: str, definition: ScenarioDefinition
    ) -> RevisionMetadata:
        metadata = self._metadata(simulation_id)
        payload = metadata.get(scenario_id)
        if payload is not None:
            current = self._parse_metadata(payload)
            actual_etag = definition_etag(definition)
            if actual_etag == current.etag:
                return current
            adopted = RevisionMetadata(
                revision=current.revision + 1,
                etag=actual_etag,
                created_at=datetime.now(UTC),
                created_by="external-change",
            )
            self._write_revision(simulation_id, scenario_id, adopted, definition)
            metadata[scenario_id] = self._dump_metadata(adopted)
            self.repository.write_json(simulation_id, "scenarios/revisions.json", metadata)
            return adopted
        adopted = RevisionMetadata(
            revision=1,
            etag=definition_etag(definition),
            created_at=datetime.now(UTC),
            created_by="legacy-import",
        )
        self._write_revision(simulation_id, scenario_id, adopted, definition)
        metadata[scenario_id] = self._dump_metadata(adopted)
        self.repository.write_json(simulation_id, "scenarios/revisions.json", metadata)
        return adopted

    def save(
        self,
        simulation_id: str,
        scenario_id: str,
        definition: ScenarioDefinition,
        actor: str,
        expected_etag: str | None = None,
    ) -> RevisionMetadata:
        with self._lock:
            return self._save(simulation_id, scenario_id, definition, actor, expected_etag)

    def _save(
        self,
        simulation_id: str,
        scenario_id: str,
        definition: ScenarioDefinition,
        actor: str,
        expected_etag: str | None = None,
    ) -> RevisionMetadata:
        scenarios = self.repository.read_scenarios(simulation_id)
        existing_payload = scenarios.get(scenario_id)
        incoming_etag = definition_etag(definition)
        metadata = self._metadata(simulation_id)
        if existing_payload is not None:
            existing = ScenarioDefinition.model_validate(existing_payload)
            current = self._current(simulation_id, scenario_id, existing)
            if expected_etag is not None and expected_etag != current.etag:
                raise ScenarioConflictError(expected_etag, current.etag, current.revision)
            if incoming_etag == current.etag:
                return current
            revision = current.revision + 1
        else:
            if expected_etag is not None:
                raise ScenarioConflictError(expected_etag, "", 0)
            revision = 1
        created = RevisionMetadata(
            revision=revision,
            etag=incoming_etag,
            created_at=datetime.now(UTC),
            created_by=actor,
        )
        self.repository.write_scenario(
            simulation_id, scenario_id, definition.model_dump(mode="json")
        )
        self._write_revision(simulation_id, scenario_id, created, definition)
        metadata = self._metadata(simulation_id)
        metadata[scenario_id] = self._dump_metadata(created)
        self.repository.write_json(simulation_id, "scenarios/revisions.json", metadata)
        return created

    def history(
        self, simulation_id: str, scenario_id: str, definition: ScenarioDefinition
    ) -> list[ScenarioRevisionSummary]:
        with self._lock:
            self._current(simulation_id, scenario_id, definition)
            directory = self.repository.path(simulation_id) / "scenarios" / "history" / scenario_id
            revisions = [self._read_revision(path) for path in directory.glob("*.json")]
            return [
                self._summary(item) for item in sorted(revisions, key=lambda item: -item.revision)
            ]

    def revision(self, simulation_id: str, scenario_id: str, revision: int) -> ScenarioRevision:
        with self._lock:
            if revision < 1:
                raise ValueError("Scenario revision must be positive")
            path = (
                self.repository.path(simulation_id)
                / "scenarios"
                / "history"
                / scenario_id
                / f"{revision}.json"
            )
            if not path.is_file():
                raise KeyError(f"Scenario revision not found: {revision}")
            return self._read_revision(path)

    def _metadata(self, simulation_id: str) -> dict[str, Any]:
        try:
            payload = self.repository.read_json(simulation_id, "scenarios/revisions.json")
        except FileNotFoundError:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("Stored scenario revision metadata must be an object")
        return payload

    def _write_revision(
        self,
        simulation_id: str,
        scenario_id: str,
        metadata: RevisionMetadata,
        definition: ScenarioDefinition,
    ) -> None:
        self.repository.write_json(
            simulation_id,
            f"scenarios/history/{scenario_id}/{metadata.revision}.json",
            {
                **self._dump_metadata(metadata),
                "simulation_id": simulation_id,
                "scenario_id": scenario_id,
                "name": definition.name,
                "state_count": len(definition.states),
                "handler_count": sum(len(state.handlers) for state in definition.states),
                "definition": definition.model_dump(mode="json"),
            },
        )

    @staticmethod
    def _parse_metadata(payload: dict[str, Any]) -> RevisionMetadata:
        return RevisionMetadata(
            revision=int(payload["revision"]),
            etag=str(payload["etag"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            created_by=str(payload["created_by"]),
        )

    @staticmethod
    def _dump_metadata(metadata: RevisionMetadata) -> dict[str, Any]:
        return {
            "revision": metadata.revision,
            "etag": metadata.etag,
            "created_at": metadata.created_at.isoformat(),
            "created_by": metadata.created_by,
        }

    @staticmethod
    def _read_revision(path: Path) -> ScenarioRevision:
        return ScenarioRevision.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _summary(revision: ScenarioRevision) -> ScenarioRevisionSummary:
        return ScenarioRevisionSummary(
            revision=revision.revision,
            etag=revision.etag,
            created_at=revision.created_at,
            created_by=revision.created_by,
            name=revision.name,
            state_count=revision.state_count,
            handler_count=revision.handler_count,
        )
