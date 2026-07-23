from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from threading import RLock

from simuloom.core.repository import WorkspaceRepository
from simuloom.models import ScenarioRelease, ScenarioRevision


def mapping_fingerprint(mappings: list[dict]) -> str:
    canonical = json.dumps(mappings, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class ScenarioReleaseStore:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository
        self._lock = RLock()

    def record(
        self,
        revision: ScenarioRevision,
        mappings: list[dict],
        actor: str,
        source_release: int | None = None,
    ) -> ScenarioRelease:
        with self._lock:
            releases = self._read(revision.simulation_id, revision.scenario_id)
            release = ScenarioRelease(
                simulation_id=revision.simulation_id,
                scenario_id=revision.scenario_id,
                release_number=len(releases) + 1,
                revision=revision.revision,
                etag=revision.etag,
                mapping_fingerprint=mapping_fingerprint(mappings),
                mapping_count=len(mappings),
                deployed_at=datetime.now(UTC),
                deployed_by=actor,
                source_release=source_release,
            )
            releases.append(release)
            self.repository.write_json(
                revision.simulation_id,
                f"scenarios/releases/{revision.scenario_id}.json",
                [item.model_dump(mode="json") for item in releases],
            )
            return release

    def list(self, simulation_id: str, scenario_id: str) -> list[ScenarioRelease]:
        with self._lock:
            return list(reversed(self._read(simulation_id, scenario_id)))

    def get(self, simulation_id: str, scenario_id: str, release_number: int) -> ScenarioRelease:
        if release_number < 1:
            raise ValueError("Scenario release number must be positive")
        with self._lock:
            releases = self._read(simulation_id, scenario_id)
            try:
                return releases[release_number - 1]
            except IndexError as exc:
                raise KeyError(f"Scenario release not found: {release_number}") from exc

    def _read(self, simulation_id: str, scenario_id: str) -> list[ScenarioRelease]:
        self.repository.validate_scenario_id(scenario_id)
        try:
            payload = self.repository.read_json(
                simulation_id, f"scenarios/releases/{scenario_id}.json"
            )
        except FileNotFoundError:
            return []
        if not isinstance(payload, list):
            raise ValueError("Stored scenario releases must be an array")
        return [ScenarioRelease.model_validate(item) for item in payload]
