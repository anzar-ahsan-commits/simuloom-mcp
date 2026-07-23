from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlsplit

from simuloom.runtime.models import (
    RuntimeCapabilities,
    RuntimeMapping,
    RuntimeResponse,
    RuntimeValueMatcher,
)


class NativeRuntimeAdapter:
    """Process-local deterministic runtime intended for development and CI."""

    def __init__(self, base_url: str = "http://localhost:8000/runtime") -> None:
        self.base_url = base_url.rstrip("/")
        self._mappings: dict[str, list[RuntimeMapping]] = {}
        self._states: dict[str, str] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(runtime="native")

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
                self._mappings.clear()
                self._states.clear()
                self._events.clear()
            self._mappings[simulation_id] = [mapping.model_copy(deep=True) for mapping in mappings]
            for mapping in mappings:
                if mapping.scenario_name is not None:
                    self._states.setdefault(mapping.scenario_name, "Started")
        return len(mappings)

    async def reset_runtime_state(self, simulation_id: str | None = None) -> None:
        async with self._lock:
            scenario_names = {
                mapping.scenario_name
                for owner, mappings in self._mappings.items()
                if simulation_id is None or owner == simulation_id
                for mapping in mappings
                if mapping.scenario_name is not None
            }
            for name in scenario_names:
                self._states[name] = "Started"
            self._events = [
                event
                for event in self._events
                if simulation_id is not None and event.get("simulationId") != simulation_id
            ]

    async def scenario_state(self, scenario_name: str) -> str | None:
        return self._states.get(scenario_name)

    async def set_scenario_state(self, scenario_name: str, state: str) -> None:
        if scenario_name not in self._states:
            raise RuntimeError(f"Scenario is not deployed: {scenario_name}")
        self._states[scenario_name] = state

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
            existing = self._mappings.get(simulation_id, [])
            retained = [mapping for mapping in existing if mapping.scenario_name != scenario_name]
            self._mappings[simulation_id] = [
                *retained,
                *(mapping.model_copy(deep=True) for mapping in mappings),
            ]
            self._states[scenario_name] = initial_state
        return len(mappings)

    async def reset_all_scenarios(self) -> None:
        async with self._lock:
            for name in self._states:
                self._states[name] = "Started"

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
                self._mappings.get(simulation_id, []), key=lambda mapping: mapping.priority
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
                    self._states[selected.scenario_name] = selected.new_state
                body = deepcopy(selected.response.json_body)
                status = selected.response.status
                response_headers = dict(selected.response.headers)
            self._events.append(
                {
                    "simulationId": simulation_id,
                    "request": {"method": method.upper(), "url": path},
                    "wasMatched": selected is not None,
                    "mappingName": selected.name if selected is not None else None,
                }
            )
        if selected is not None and selected.response.delay_ms:
            await asyncio.sleep(selected.response.delay_ms / 1000)
        elapsed = round((perf_counter() - started) * 1000, 2)
        return RuntimeResponse(status, body, response_headers, elapsed)

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(event)
            for event in self._events
            if simulation_id is None or event.get("simulationId") == simulation_id
        ]

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
            if self._states.get(mapping.scenario_name, "Started") != mapping.required_state:
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
