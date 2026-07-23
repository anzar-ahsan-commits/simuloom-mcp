import json
import subprocess
from pathlib import Path

import pytest

from simuloom.core.gitops import build_snapshot, validate_snapshot
from simuloom.core.repository import WorkspaceRepository


def test_snapshot_is_deterministic_and_detects_tampering(tmp_path: Path) -> None:
    repository = WorkspaceRepository(tmp_path / "workspace")
    simulation_id = repository.create("GitOps Demo", {"openapi": "3.1.0"}, "abc123")
    repository.write_scenario(simulation_id, "order-flow", {"name": "Order flow"})

    first = build_snapshot(repository, simulation_id)
    second = build_snapshot(repository, simulation_id)

    assert first == second
    validate_snapshot(first)
    first["spec"]["activeProfile"] = "slow"
    with pytest.raises(ValueError, match="integrity"):
        validate_snapshot(first)


def test_gitops_cli_validates_and_reports_drift(tmp_path: Path) -> None:
    repository = WorkspaceRepository(tmp_path / "workspace")
    simulation_id = repository.create("GitOps Demo", {"openapi": "3.1.0"}, "abc123")
    expected = build_snapshot(repository, simulation_id)
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected))
    repository.write_scenario(simulation_id, "new-flow", {"name": "New flow"})
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(json.dumps(build_snapshot(repository, simulation_id)))

    validated = subprocess.run(
        ["uv", "run", "simuloom-gitops", "validate", str(expected_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    drift = subprocess.run(
        ["uv", "run", "simuloom-gitops", "diff", str(expected_path), str(actual_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert validated.returncode == 0
    assert json.loads(validated.stdout)["valid"] is True
    assert drift.returncode == 1
    assert json.loads(drift.stdout)["drift"] is True
