from pathlib import Path

from test_scenarios import ScenarioWireMock

from simuloom.core.job_runner import JobRunner
from simuloom.core.platform_store import PlatformStore
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


def test_job_runner_claims_each_job_once(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    service = SimulationService(
        WorkspaceRepository(tmp_path / "workspace"),
        ScenarioWireMock(),  # type: ignore[arg-type]
    )
    runner = JobRunner(store, service)
    workspace = store.create_workspace("Jobs", "owner")
    job = store.create_job(workspace["id"], "workspace-backup", {})

    assert runner.execute_job(job["id"]) is True
    assert runner.execute_job(job["id"]) is False
    completed = store.get_job(job["id"])
    assert completed["status"] == "succeeded"
    assert completed["progress"] == 100


def test_next_job_claim_is_atomic(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    workspace = store.create_workspace("Jobs", "owner")
    job = store.create_job(workspace["id"], "workspace-backup", {})

    claimed = store.claim_next_job()

    assert claimed is not None and claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert store.claim_next_job() is None
