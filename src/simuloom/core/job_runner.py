from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from simuloom.core.gitops import build_snapshot
from simuloom.core.platform_store import PlatformStore
from simuloom.core.service import SimulationService


class JobRunner:
    def __init__(self, store: PlatformStore, service: SimulationService) -> None:
        self.store = store
        self.service = service
        self._stop = asyncio.Event()

    def execute_job(self, job_id: str) -> bool:
        job = self.store.claim_job(job_id)
        if job is None:
            return False
        self._execute_claimed(job)
        return True

    def _execute_claimed(self, job: dict[str, Any]) -> None:
        try:
            if job["kind"] == "workspace-backup":
                data = self.service.workspace_backup()
                result = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            elif job["kind"] == "gitops-snapshot":
                simulation_id = str(job["payload"]["simulation_id"])
                snapshot = build_snapshot(self.service.repository, simulation_id)
                result = {
                    "simulation_id": simulation_id,
                    "integrity": snapshot["integrity"],
                    "scenario_count": len(snapshot["spec"]["scenarios"]),
                }
            else:
                raise ValueError(f"Unsupported job kind: {job['kind']}")
            self.store.update_job(job["id"], "succeeded", 100, result=result)
        except Exception as exc:
            self.store.update_job(job["id"], "failed", 100, error=str(exc)[:500])

    async def run(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next_job()
            if job is not None:
                await asyncio.to_thread(self._execute_claimed, job)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
