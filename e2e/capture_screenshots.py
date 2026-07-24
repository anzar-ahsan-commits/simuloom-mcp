#!/usr/bin/env python3
"""Capture reproducible operator-console screenshots from a running SimuLoom instance.

This is a standalone utility, not a pytest test: it deliberately writes files instead of
asserting, so it can't fail a CI run just because a marketing screenshot looks different.
See docs/e2e-testing.md for how to review and adopt its output as new launch-guide images.

Usage:
    uv run --extra e2e python e2e/capture_screenshots.py \
        [--base-url http://localhost:8000] [--out DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import yaml
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
ORDER_LIFECYCLE = REPO_ROOT / "examples" / "order-lifecycle"


def seed_simulation(base_url: str) -> dict:
    with httpx.Client(base_url=f"{base_url}/api/v1", timeout=30) as client:
        with (ORDER_LIFECYCLE / "openapi.yaml").open("rb") as contract_file:
            response = client.post(
                "/simulations/from-contract",
                data={"name": "Launch guide screenshot capture"},
                files={"contract": ("openapi.yaml", contract_file, "application/yaml")},
            )
        response.raise_for_status()
        simulation = response.json()
        simulation_id = simulation["id"]

        scenario = yaml.safe_load((ORDER_LIFECYCLE / "scenario.yaml").read_text())
        client.put(
            f"/simulations/{simulation_id}/scenarios/order-lifecycle", json=scenario
        ).raise_for_status()
        client.post(
            f"/simulations/{simulation_id}/scenarios/order-lifecycle/compile"
        ).raise_for_status()
        client.post(
            f"/simulations/{simulation_id}/scenarios/order-lifecycle/deploy"
        ).raise_for_status()
        client.post(
            f"/simulations/{simulation_id}/validate",
            json={"max_dataset_cases": 3, "reset_runtime_state": True},
        ).raise_for_status()
        return simulation


def capture(base_url: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    simulation = seed_simulation(base_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{base_url}/ui")
        page.wait_for_function("document.querySelector('#runtime-name')?.textContent !== '—'")

        page.screenshot(path=out_dir / "overview.png", full_page=True)

        page.click('.nav-item[data-view="scenarios"]')
        page.select_option("#designer-simulation", simulation["id"])
        page.click('#designer-scenario-list button[data-designer-scenario="order-lifecycle"]')
        page.wait_for_selector("#scenario-graph g[role='button']")
        page.screenshot(path=out_dir / "scenario-designer.png", full_page=True)

        page.click('.nav-item[data-view="simulations"]')
        page.click(f'#simulation-list button[data-simulation="{simulation["id"]}"]')
        page.click('[data-action="report"]')
        page.wait_for_selector("#result-drawer:not([hidden])")
        page.screenshot(path=out_dir / "validation-evidence.png", full_page=True)

        browser.close()

    print(f"Captured screenshots into {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "images" / "e2e-captures")
    args = parser.parse_args()
    capture(args.base_url, args.out)


if __name__ == "__main__":
    main()
