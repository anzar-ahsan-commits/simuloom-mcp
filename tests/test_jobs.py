from pathlib import Path

from simuloom.core.platform_store import PlatformStore


def test_jobs_persist_progress_results_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "platform.db"
    first = PlatformStore(path)
    workspace = first.create_workspace("Jobs", "owner")
    job = first.create_job(workspace["id"], "workspace-backup", {})
    first.update_job(job["id"], "running", 25)
    first.update_job(job["id"], "succeeded", 100, result={"bytes": 123})
    first.close()

    second = PlatformStore(path)
    restored = second.get_job(job["id"])

    assert restored["status"] == "succeeded"
    assert restored["progress"] == 100
    assert restored["result"] == {"bytes": 123}
    assert second.list_jobs(workspace["id"])[0]["id"] == job["id"]


def test_running_job_is_requeued_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "platform.db"
    first = PlatformStore(path)
    workspace = first.create_workspace("Jobs", "owner")
    job = first.create_job(workspace["id"], "workspace-backup", {})
    first.update_job(job["id"], "running", 40)
    first.close()

    second = PlatformStore(path)
    recovered = second.get_job(job["id"])

    assert recovered["status"] == "queued"
    assert recovered["progress"] == 0
    assert "requeued" in recovered["error"]
