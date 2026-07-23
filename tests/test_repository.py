from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from simuloom.core.repository import WorkspaceRepository


def create_repository(tmp_path: Path) -> tuple[WorkspaceRepository, str]:
    repository = WorkspaceRepository(tmp_path)
    simulation_id = repository.create("Repository test", {"openapi": "3.1.0"}, "fingerprint")
    return repository, simulation_id


def test_artifact_paths_cannot_escape_simulation(tmp_path: Path) -> None:
    repository, simulation_id = create_repository(tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        repository.write_text(simulation_id, "../../outside.txt", "unsafe")

    assert not (tmp_path.parent / "outside.txt").exists()


def test_atomic_write_does_not_leave_temporary_files(tmp_path: Path) -> None:
    repository, simulation_id = create_repository(tmp_path)

    repository.write_json(simulation_id, "reports/result.json", {"complete": True})

    assert repository.read_json(simulation_id, "reports/result.json") == {"complete": True}
    assert not list(repository.path(simulation_id).rglob("*.tmp"))


def test_failed_atomic_replace_preserves_previous_file(tmp_path: Path, monkeypatch) -> None:
    repository, simulation_id = create_repository(tmp_path)
    repository.write_text(simulation_id, "reports/result.txt", "previous")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("simuloom.core.repository.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated"):
        repository.write_text(simulation_id, "reports/result.txt", "next")

    assert repository.read_text(simulation_id, "reports/result.txt") == "previous"
    assert not list(repository.path(simulation_id).rglob("*.tmp"))


def test_concurrent_scenario_updates_do_not_lose_data(tmp_path: Path) -> None:
    repository, simulation_id = create_repository(tmp_path)
    second_repository = WorkspaceRepository(tmp_path)

    def write(index: int) -> None:
        selected = repository if index % 2 else second_repository
        selected.write_scenario(
            simulation_id,
            f"scenario-{index}",
            {"name": f"Scenario {index}"},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(24)))

    assert len(repository.read_scenarios(simulation_id)) == 24


def test_existing_workspace_is_adopted_with_current_schema(tmp_path: Path) -> None:
    (tmp_path / "legacy-simulation").mkdir()
    (tmp_path / "legacy-simulation" / "simulation.json").write_text("{}")

    repository = WorkspaceRepository(tmp_path)

    assert repository.diagnostics() == {
        "format": "simuloom-workspace",
        "schema_version": 1,
        "supported_schema_version": 1,
        "writable": True,
        "simulation_count": 1,
    }


def test_newer_workspace_schema_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".simuloom-workspace.json").write_text(
        '{"format":"simuloom-workspace","schemaVersion":999}'
    )

    with pytest.raises(RuntimeError, match="newer than supported"):
        WorkspaceRepository(tmp_path)
