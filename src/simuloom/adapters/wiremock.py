from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from simuloom.runtime.models import RuntimeCapabilities, RuntimeMapping, RuntimeResponse
from simuloom.runtime.translation import to_wiremock_mapping


class WireMockClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(runtime="wiremock", persistent=True, storage="wiremock")

    async def health(self) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/mappings")
            return response.is_success

    async def deploy(
        self,
        mappings: list[RuntimeMapping] | list[dict[str, Any]],
        reset_existing: bool,
        simulation_id: str | None = None,
    ) -> int:
        del simulation_id
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            if reset_existing:
                response = await client.delete(f"{self.base_url}/__admin/mappings")
                response.raise_for_status()
            for mapping in mappings:
                payload = (
                    to_wiremock_mapping(mapping) if isinstance(mapping, RuntimeMapping) else mapping
                )
                response = await client.post(f"{self.base_url}/__admin/mappings", json=payload)
                response.raise_for_status()
        return len(mappings)

    async def reset_runtime_state(self, simulation_id: str | None = None) -> None:
        del simulation_id
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            scenarios = await client.post(f"{self.base_url}/__admin/scenarios/reset")
            scenarios.raise_for_status()
            requests = await client.delete(f"{self.base_url}/__admin/requests")
            requests.raise_for_status()

    async def scenario_state(self, scenario_name: str) -> str | None:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/scenarios")
            response.raise_for_status()
            for scenario in response.json().get("scenarios", []):
                if scenario.get("name") == scenario_name:
                    return str(scenario.get("state"))
        return None

    async def set_scenario_state(self, scenario_name: str, state: str) -> None:
        encoded = quote(scenario_name, safe=":")
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.put(
                f"{self.base_url}/__admin/scenarios/{encoded}/state",
                json={"state": state},
            )
            response.raise_for_status()

    async def remove_scenario_mappings(self, scenario_name: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/mappings")
            response.raise_for_status()
            mappings = response.json().get("mappings", [])
            for mapping in mappings:
                if mapping.get("scenarioName") == scenario_name and mapping.get("id"):
                    deleted = await client.delete(
                        f"{self.base_url}/__admin/mappings/{mapping['id']}"
                    )
                    deleted.raise_for_status()

    async def deploy_scenario(
        self,
        mappings: list[RuntimeMapping] | list[dict[str, Any]],
        scenario_name: str,
        initial_state: str,
        simulation_id: str | None = None,
    ) -> int:
        del simulation_id
        await self.remove_scenario_mappings(scenario_name)
        try:
            deployed = await self.deploy(mappings, reset_existing=False)
            await self.set_scenario_state(scenario_name, initial_state)
            return deployed
        except Exception:
            await self.remove_scenario_mappings(scenario_name)
            raise

    async def reset_all_scenarios(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(f"{self.base_url}/__admin/scenarios/reset")
            response.raise_for_status()

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        simulation_id: str | None = None,
    ) -> RuntimeResponse:
        del simulation_id
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.request(
                method, f"{self.base_url}{path}", json=json_body, headers=headers
            )
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            return RuntimeResponse(
                status_code=response.status_code,
                body=body,
                headers=dict(response.headers),
                elapsed_ms=round(response.elapsed.total_seconds() * 1000, 2),
            )

    async def serve_events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        del simulation_id
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/requests")
            response.raise_for_status()
            payload = response.json()
            return payload.get("requests", [])
