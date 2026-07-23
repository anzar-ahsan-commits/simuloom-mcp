from __future__ import annotations

from typing import Any, Protocol

from simuloom.runtime.models import RuntimeCapabilities, RuntimeMapping, RuntimeResponse


class RuntimeAdapter(Protocol):
    base_url: str

    def capabilities(self) -> RuntimeCapabilities: ...

    async def health(self) -> bool: ...

    async def deploy(
        self,
        mappings: list[RuntimeMapping],
        reset_existing: bool,
        simulation_id: str | None = None,
    ) -> int: ...

    async def reset_runtime_state(self, simulation_id: str | None = None) -> None: ...

    async def scenario_state(self, scenario_name: str) -> str | None: ...

    async def set_scenario_state(self, scenario_name: str, state: str) -> None: ...

    async def deploy_scenario(
        self,
        mappings: list[RuntimeMapping],
        scenario_name: str,
        initial_state: str,
        simulation_id: str | None = None,
    ) -> int: ...

    async def reset_all_scenarios(self) -> None: ...

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        simulation_id: str | None = None,
    ) -> RuntimeResponse: ...

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]: ...
