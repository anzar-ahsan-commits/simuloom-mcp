from __future__ import annotations

from copy import deepcopy
from typing import Any

from simuloom.runtime.models import RuntimeMapping


class MemoryRuntimeStore:
    persistent = False
    storage = "memory"

    def __init__(self, journal_limit: int = 1_000) -> None:
        if journal_limit < 1:
            raise ValueError("journal_limit must be positive")
        self.journal_limit = journal_limit
        self._mappings: dict[str, list[RuntimeMapping]] = {}
        self._states: dict[str, tuple[str, str]] = {}
        self._events: list[dict[str, Any]] = []

    def close(self) -> None:
        return None

    def clear(self) -> None:
        self._mappings.clear()
        self._states.clear()
        self._events.clear()

    def mappings(self, simulation_id: str) -> list[RuntimeMapping]:
        return [item.model_copy(deep=True) for item in self._mappings.get(simulation_id, [])]

    def replace_mappings(self, simulation_id: str, mappings: list[RuntimeMapping]) -> None:
        self._mappings[simulation_id] = [item.model_copy(deep=True) for item in mappings]

    def scenario_names(self, simulation_id: str | None = None) -> list[str]:
        return sorted(
            name
            for name, (owner, _) in self._states.items()
            if simulation_id is None or owner == simulation_id
        )

    def scenario_state(self, scenario_name: str) -> str | None:
        stored = self._states.get(scenario_name)
        return stored[1] if stored is not None else None

    def ensure_scenario_state(self, simulation_id: str, scenario_name: str, state: str) -> None:
        self._states.setdefault(scenario_name, (simulation_id, state))

    def set_scenario_state(self, scenario_name: str, state: str) -> None:
        stored = self._states.get(scenario_name)
        if stored is None:
            raise RuntimeError(f"Scenario is not deployed: {scenario_name}")
        self._states[scenario_name] = (stored[0], state)

    def append_event(self, simulation_id: str, event: dict[str, Any]) -> None:
        self._events.append(deepcopy(event))
        owned = [
            index
            for index, item in enumerate(self._events)
            if item.get("simulationId") == simulation_id
        ]
        for index in reversed(owned[: -self.journal_limit]):
            del self._events[index]

    def events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(event)
            for event in self._events
            if simulation_id is None or event.get("simulationId") == simulation_id
        ]

    def clear_events(self, simulation_id: str | None = None) -> None:
        if simulation_id is None:
            self._events.clear()
            return
        self._events = [
            event for event in self._events if event.get("simulationId") != simulation_id
        ]
