"""Automated accessibility scans (axe-core) across the console's primary states. On failure, the
assertion message names the offending rule and DOM selector so the affected control is obvious
without re-running the scan interactively."""

from __future__ import annotations

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

axe = Axe()


def _format_violations(violations: list[dict]) -> str:
    lines = []
    for violation in violations:
        targets = ", ".join(
            node["target"][0] for node in violation.get("nodes", []) if node.get("target")
        )
        lines.append(f"[{violation['impact']}] {violation['id']}: {violation['help']} -> {targets}")
    return "\n".join(lines)


def assert_no_serious_violations(page: Page) -> None:
    results = axe.run(page)
    serious = [
        violation
        for violation in results.response["violations"]
        if violation.get("impact") in {"serious", "critical"}
    ]
    assert not serious, f"Accessibility violations found:\n{_format_violations(serious)}"


def test_overview_view_has_no_serious_violations(console: Page):
    assert_no_serious_violations(console)


def test_simulation_detail_has_no_serious_violations(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="simulations"]')
    console.click(f'#simulation-list button[data-simulation="{seeded_simulation["id"]}"]')
    assert_no_serious_violations(console)


def test_scenario_designer_has_no_serious_violations(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="scenarios"]')
    console.select_option("#designer-simulation", seeded_simulation["id"])
    console.click('#designer-scenario-list button[data-designer-scenario="order-lifecycle"]')
    assert_no_serious_violations(console)


def test_copilot_view_has_no_serious_violations(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="copilot"]')
    console.select_option("#copilot-simulation", seeded_simulation["id"])
    console.click("#new-chat-button")
    assert_no_serious_violations(console)
