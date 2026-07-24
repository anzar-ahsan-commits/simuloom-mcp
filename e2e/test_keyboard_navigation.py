"""Covers keyboard operability: the skip link, tabbing through primary navigation, activating a
view with the keyboard alone, a visible change on focus, and accessible names on icon-only
controls.

Focus is driven with real Tab key presses rather than locator.focus() — Chromium only applies
:focus-visible (the pseudo-class this console's CSS actually styles) for focus that followed
keyboard input, so a script-driven .focus() would not exercise the same style path a keyboard
user hits.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect


def _tab_to(page: Page, selector: str, max_tabs: int = 20) -> None:
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        if page.evaluate("(sel) => document.activeElement?.matches(sel)", selector):
            return
    raise AssertionError(f"could not reach {selector!r} within {max_tabs} Tab presses")


def test_skip_link_is_first_focusable_and_reveals_on_focus(console: Page):
    skip_link = console.locator(".skip-link")
    hidden_top = skip_link.evaluate("(el) => parseFloat(getComputedStyle(el).top)")
    assert hidden_top < 0, "skip link should sit off-screen until focused"

    console.keyboard.press("Tab")
    expect(skip_link).to_be_focused()
    focused_top = skip_link.evaluate("(el) => parseFloat(getComputedStyle(el).top)")
    assert focused_top > hidden_top, "skip link should move into view when focused"
    assert skip_link.get_attribute("href") == "#workspace"


def test_nav_items_are_reachable_and_operable_by_keyboard(console: Page):
    _tab_to(console, '.nav-item[data-view="simulations"]')
    expect(console.locator('.nav-item[data-view="simulations"]')).to_be_focused()

    console.keyboard.press("Enter")
    expect(console.locator("#simulations-view")).to_have_class("view active")


def test_focused_nav_item_has_a_visible_focus_indicator(console: Page):
    target = console.locator('.nav-item[data-view="copilot"]')
    unfocused_style = target.evaluate(
        "(el) => { const s = getComputedStyle(el); return s.backgroundColor + '|' + s.color; }"
    )

    _tab_to(console, '.nav-item[data-view="copilot"]')
    expect(target).to_be_focused()
    focused_style = target.evaluate(
        "(el) => { const s = getComputedStyle(el); return s.backgroundColor + '|' + s.color; }"
    )
    assert focused_style != unfocused_style, (
        "keyboard focus on a nav item must be visually distinguishable from its resting state"
    )


def test_icon_only_controls_have_accessible_names(console: Page):
    expect(console.locator("a.brand")).to_have_attribute("aria-label", "SimuLoom home")

    console.click("#new-simulation-button")
    close_button = console.locator('#create-dialog button[data-close="create-dialog"][aria-label]')
    expect(close_button).to_have_attribute("aria-label", "Close")
    expect(close_button).to_have_text("×")
