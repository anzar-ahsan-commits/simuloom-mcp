"""Browser-level fixtures for the operator console.

These tests exercise a real, already-running SimuLoom instance (see docs/e2e-testing.md) — they
do not start the application themselves. They assume authentication is disabled, matching
docker-compose.yml's default, so every control is enabled without needing to inject a session key.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from playwright.sync_api import Page

REPO_ROOT = Path(__file__).resolve().parent.parent
ORDER_LIFECYCLE = REPO_ROOT / "examples" / "order-lifecycle"


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("SIMULOOM_E2E_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def api_client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"{base_url}/api/v1", timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
def seeded_simulation(api_client: httpx.Client) -> dict:
    """A simulation with the order-lifecycle scenario compiled and deployed, seeded via REST.

    Tests that only need an existing simulation to select and inspect use this instead of
    repeating the create-simulation flow, which test_console_navigation.py covers end to end
    through the actual upload dialog.
    """
    with (ORDER_LIFECYCLE / "openapi.yaml").open("rb") as contract_file:
        response = api_client.post(
            "/simulations/from-contract",
            data={"name": "E2E seeded order lifecycle"},
            files={"contract": ("openapi.yaml", contract_file, "application/yaml")},
        )
    response.raise_for_status()
    simulation = response.json()
    simulation_id = simulation["id"]

    scenario = yaml.safe_load((ORDER_LIFECYCLE / "scenario.yaml").read_text())
    scenario_url = f"/simulations/{simulation_id}/scenarios/order-lifecycle"
    api_client.put(scenario_url, json=scenario).raise_for_status()
    api_client.post(f"{scenario_url}/compile").raise_for_status()
    api_client.post(f"{scenario_url}/deploy").raise_for_status()

    return simulation


@pytest.fixture
def console(page: Page, base_url: str) -> Page:
    page.goto(f"{base_url}/ui")
    page.wait_for_function("document.querySelector('#runtime-name')?.textContent !== '—'")
    return page
