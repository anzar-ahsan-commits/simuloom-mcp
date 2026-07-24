"""Covers scenario inspection through the visual designer: selecting a simulation, choosing an
already-deployed scenario, and rendering its state graph."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_scenario_inspection_renders_state_graph(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="scenarios"]')
    console.select_option("#designer-simulation", seeded_simulation["id"])

    scenario_button = console.locator(
        '#designer-scenario-list button[data-designer-scenario="order-lifecycle"]'
    )
    expect(scenario_button).to_be_visible()
    scenario_button.click()

    graph = console.locator("#scenario-graph")
    expect(graph).to_be_visible()
    expect(graph).to_have_attribute("role", "img")
    # The order-lifecycle example declares four states: NOT_CREATED, PENDING, PAID, SHIPPED.
    expect(graph.locator("g[role='button']")).to_have_count(4)
    expect(graph.locator('g[aria-label="Select state NOT_CREATED"]')).to_be_visible()
    expect(graph.locator('g[aria-label="Select state SHIPPED"]')).to_be_visible()

    diagnostics = console.locator("#designer-diagnostics")
    expect(diagnostics).to_be_visible()
