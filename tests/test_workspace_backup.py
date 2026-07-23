import io
import zipfile
from pathlib import Path

import pytest
from test_scenarios import ScenarioWireMock, contract, definition_payload

from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


def service_at(path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(path), ScenarioWireMock())  # type: ignore[arg-type]


def test_workspace_backup_round_trip_without_overwrite(tmp_path: Path) -> None:
    source = service_at(tmp_path / "source")
    simulation = source.create("Backup", contract())
    source.configure_scenario(
        simulation.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    data = source.workspace_backup()
    target = service_at(tmp_path / "target")

    restored = target.restore_workspace(data, "admin")

    assert restored.restored_files > 0
    assert (
        target.get_scenario(simulation.id, "order-lifecycle").definition.name == "Order lifecycle"
    )
    with pytest.raises(ValueError, match="overwrite"):
        target.restore_workspace(data, "admin")


def test_workspace_restore_rejects_traversal_before_writes(tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("safe/file.json", "{}")
        archive.writestr("../escape.json", "{}")
    target = service_at(tmp_path / "target")

    with pytest.raises(ValueError, match="Unsafe"):
        target.restore_workspace(output.getvalue(), "admin")

    assert not (tmp_path / "target" / "safe").exists()
    assert not (tmp_path / "escape.json").exists()
