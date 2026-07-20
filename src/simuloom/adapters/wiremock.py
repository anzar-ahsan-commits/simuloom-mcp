from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class RuntimeResponse:
    status_code: int
    body: Any
    headers: dict[str, str]
    elapsed_ms: float


class WireMockClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/mappings")
            return response.is_success

    async def deploy(self, mappings: list[dict[str, Any]], reset_existing: bool) -> int:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            if reset_existing:
                response = await client.delete(f"{self.base_url}/__admin/mappings")
                response.raise_for_status()
            for mapping in mappings:
                response = await client.post(f"{self.base_url}/__admin/mappings", json=mapping)
                response.raise_for_status()
        return len(mappings)

    async def reset_runtime_state(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            scenarios = await client.post(f"{self.base_url}/__admin/scenarios/reset")
            scenarios.raise_for_status()
            requests = await client.delete(f"{self.base_url}/__admin/requests")
            requests.raise_for_status()

    async def execute(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> RuntimeResponse:
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

    async def serve_events(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/__admin/requests")
            response.raise_for_status()
            payload = response.json()
            return payload.get("requests", [])
