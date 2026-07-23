from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlsplit

from simuloom.runtime.memory import MemoryRuntimeStore
from simuloom.runtime.models import (
    RuntimeCapabilities,
    RuntimeMapping,
    RuntimeResponse,
    RuntimeValueMatcher,
)
from simuloom.runtime.store import RuntimeStore


class NativeRuntimeAdapter:
    """Deterministic embedded runtime with pluggable durable or ephemeral storage."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/runtime",
        store: RuntimeStore | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store = store or MemoryRuntimeStore()
        self._lock = asyncio.Lock()

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            runtime="native",
            persistent=self.store.persistent,
            storage=self.store.storage,
            journal_limit=getattr(self.store, "journal_limit", None),
        )

    async def health(self) -> bool:
        return True

    async def deploy(
        self,
        mappings: list[RuntimeMapping],
        reset_existing: bool,
        simulation_id: str | None = None,
    ) -> int:
        if simulation_id is None:
            raise ValueError("Native runtime deployment requires a simulation_id")
        async with self._lock:
            if reset_existing:
                self.store.clear()
            self.store.replace_mappings(simulation_id, mappings)
            for mapping in mappings:
                if mapping.scenario_name is not None:
                    self.store.ensure_scenario_state(
                        simulation_id, mapping.scenario_name, "Started"
                    )
        return len(mappings)

    async def reset_runtime_state(self, simulation_id: str | None = None) -> None:
        async with self._lock:
            for name in self.store.scenario_names(simulation_id):
                self.store.set_scenario_state(name, "Started")
            self.store.clear_events(simulation_id)

    async def scenario_state(self, scenario_name: str) -> str | None:
        return self.store.scenario_state(scenario_name)

    async def set_scenario_state(self, scenario_name: str, state: str) -> None:
        self.store.set_scenario_state(scenario_name, state)

    async def deploy_scenario(
        self,
        mappings: list[RuntimeMapping],
        scenario_name: str,
        initial_state: str,
        simulation_id: str | None = None,
    ) -> int:
        if simulation_id is None:
            raise ValueError("Native scenario deployment requires a simulation_id")
        async with self._lock:
            existing = self.store.mappings(simulation_id)
            retained = [mapping for mapping in existing if mapping.scenario_name != scenario_name]
            self.store.replace_mappings(
                simulation_id,
                [
                    *retained,
                    *(mapping.model_copy(deep=True) for mapping in mappings),
                ],
            )
            self.store.ensure_scenario_state(simulation_id, scenario_name, initial_state)
            self.store.set_scenario_state(scenario_name, initial_state)
        return len(mappings)

    async def reset_all_scenarios(self) -> None:
        async with self._lock:
            for name in self.store.scenario_names():
                self.store.set_scenario_state(name, "Started")

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        simulation_id: str | None = None,
    ) -> RuntimeResponse:
        if simulation_id is None:
            raise ValueError("Native runtime execution requires a simulation_id")
        started = perf_counter()
        split = urlsplit(path)
        query = {
            name: values[-1]
            for name, values in parse_qs(split.query, keep_blank_values=True).items()
        }
        supplied_headers = {name.lower(): value for name, value in (headers or {}).items()}
        async with self._lock:
            candidates = sorted(
                self.store.mappings(simulation_id), key=lambda mapping: mapping.priority
            )
            selected = next(
                (
                    mapping
                    for mapping in candidates
                    if self._matches(
                        mapping,
                        method.upper(),
                        split.path,
                        query,
                        supplied_headers,
                        json_body,
                    )
                ),
                None,
            )
            if selected is None:
                body = {"code": "NO_MATCH", "synthetic": True}
                status = 404
                response_headers = {"content-type": "application/json"}
            else:
                if selected.new_state is not None and selected.scenario_name is not None:
                    self.store.set_scenario_state(selected.scenario_name, selected.new_state)
                body = deepcopy(selected.response.json_body)
                status = selected.response.status
                response_headers = dict(selected.response.headers)
                if selected.response.fault:
                    body = {
                        "code": "INJECTED_FAULT",
                        "fault": selected.response.fault,
                        "synthetic": True,
                    }
                    status = 503
                    response_headers["x-simuloom-fault"] = selected.response.fault
            self.store.append_event(
                simulation_id,
                {
                    "simulationId": simulation_id,
                    "request": {"method": method.upper(), "url": path},
                    "wasMatched": selected is not None,
                    "mappingName": selected.name if selected is not None else None,
                },
            )
        if selected is not None and selected.response.delay_ms:
            await asyncio.sleep(selected.response.delay_ms / 1000)
        elapsed = round((perf_counter() - started) * 1000, 2)
        return RuntimeResponse(status, body, response_headers, elapsed)

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.events(simulation_id)

    def _matches(
        self,
        mapping: RuntimeMapping,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
        body: Any,
    ) -> bool:
        request = mapping.request
        if request.method != method:
            return False
        if request.path is not None and request.path != path:
            return False
        if request.path_pattern is not None and re.fullmatch(request.path_pattern, path) is None:
            return False
        if not self._values_match(request.query, query):
            return False
        if not self._values_match(
            {name.lower(): matcher for name, matcher in request.headers.items()}, headers
        ):
            return False
        if request.match_body and request.json_body != body:
            return False
        if mapping.scenario_name is not None and mapping.required_state is not None:
            if (
                self.store.scenario_state(mapping.scenario_name) or "Started"
            ) != mapping.required_state:
                return False
        return True

    @staticmethod
    def _values_match(expected: dict[str, RuntimeValueMatcher], actual: dict[str, str]) -> bool:
        for name, matcher in expected.items():
            if matcher.absent and name in actual:
                return False
            if not matcher.absent and actual.get(name) != matcher.equal_to:
                return False
        return True
