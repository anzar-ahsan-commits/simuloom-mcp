"""Covers the console's primary navigation, simulation creation, selection, and lifecycle
controls — the golden path a new evaluator follows through the operator console."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "examples" / "order-lifecycle" / "openapi.yaml"


def test_primary_navigation_switches_views(console: Page):
    for view in ["simulations", "scenarios", "workspaces", "copilot", "overview"]:
        console.click(f'.nav-item[data-view="{view}"]')
        expect(console.locator(f"#{view}-view")).to_have_class("view active")
        expect(console.locator(f'.nav-item[data-view="{view}"]')).to_have_class("nav-item active")


def test_create_simulation_from_uploaded_contract(console: Page):
    console.click("#new-simulation-button")
    dialog = console.locator("#create-dialog")
    expect(dialog).to_be_visible()

    dialog.locator('input[name="name"]').fill("E2E uploaded order lifecycle")
    dialog.locator('input[name="contract"]').set_input_files(str(CONTRACT_PATH))
    dialog.locator('button[type="submit"]').click()

    expect(dialog).to_be_hidden()
    expect(console.locator("#notice")).to_contain_text("Simulation workspace created")
    # Creating a simulation selects it and switches to the simulation detail workspace.
    expect(console.locator("#simulations-view")).to_have_class("view active")
    expect(console.locator("#simulation-detail h2")).to_contain_text("E2E uploaded order lifecycle")


def test_select_simulation_renders_workflow_sections(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="simulations"]')
    console.click(f'#simulation-list button[data-simulation="{seeded_simulation["id"]}"]')

    detail = console.locator("#simulation-detail")
    expect(detail.locator("h2")).to_contain_text(seeded_simulation["name"])
    for heading in [
        "1. Synthetic data",
        "2. Runtime bundle",
        "3. Behavior",
        "4. Validation",
        "5. Evidence",
        "6. Scenario state",
    ]:
        expect(detail.locator("h3", has_text=heading)).to_be_visible()


def test_lifecycle_controls_generate_compile_deploy(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="simulations"]')
    console.click(f'#simulation-list button[data-simulation="{seeded_simulation["id"]}"]')
    detail = console.locator("#simulation-detail")

    for action, expected_notice in [
        ("generate", "completed"),
        ("compile", "completed"),
        ("deploy", "completed"),
    ]:
        detail.locator(f'[data-action="{action}"]').click()
        expect(console.locator("#notice")).to_contain_text(expected_notice)
        expect(console.locator("#notice")).not_to_have_class("error")
