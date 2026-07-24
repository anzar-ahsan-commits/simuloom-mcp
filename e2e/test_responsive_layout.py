"""Covers the console's two critical responsive states: the desktop sidebar layout and the
mobile breakpoint (<=760px) where the sidebar collapses into a horizontal bar."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def _no_horizontal_overflow(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_desktop_layout(console: Page):
    console.set_viewport_size({"width": 1440, "height": 900})
    assert console.locator(".app-shell").evaluate("(el) => getComputedStyle(el).display") == "grid"
    assert console.locator(".sidebar").evaluate("(el) => getComputedStyle(el).position") == "sticky"
    assert _no_horizontal_overflow(console)


def test_mobile_layout_collapses_sidebar_without_hiding_navigation(console: Page):
    console.set_viewport_size({"width": 375, "height": 667})
    assert console.locator(".app-shell").evaluate("(el) => getComputedStyle(el).display") == "block"
    assert console.locator(".sidebar").evaluate("(el) => getComputedStyle(el).position") == "static"
    assert _no_horizontal_overflow(console)

    # The numeric index labels hide at this width, but every nav control stays visible and its
    # accessible name (the view name text) survives outside the hidden <span>.
    for view, label in [
        ("overview", "Overview"),
        ("simulations", "Simulations"),
        ("scenarios", "Scenarios"),
        ("workspaces", "Team Hub"),
        ("copilot", "AI Copilot"),
    ]:
        nav_item = console.locator(f'.nav-item[data-view="{view}"]')
        expect(nav_item).to_be_visible()
        expect(nav_item).to_contain_text(label)
