"""Covers Copilot conversation selection: creating and selecting a thread does not require the
optional local AI to be enabled or reachable, so this runs without any external AI dependency."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_create_and_select_copilot_conversation(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="copilot"]')
    expect(console.locator("#copilot-ai-status")).to_be_visible()

    console.select_option("#copilot-simulation", seeded_simulation["id"])
    console.click("#new-chat-button")

    active_thread = console.locator("#copilot-thread-list button[data-chat-thread].active")
    expect(active_thread).to_have_count(1)
    expect(console.locator("#copilot-title")).to_contain_text(seeded_simulation["name"])
    expect(console.locator("#copilot-input")).to_be_focused()
    first_thread_id = active_thread.get_attribute("data-chat-thread")

    console.click("#new-chat-button")
    expect(console.locator("#copilot-thread-list button[data-chat-thread]")).to_have_count(2)
    new_active_thread = console.locator("#copilot-thread-list button[data-chat-thread].active")
    expect(new_active_thread).to_have_count(1)
    second_thread_id = new_active_thread.get_attribute("data-chat-thread")
    assert second_thread_id != first_thread_id

    # Selecting the first conversation again makes it the active one instead.
    first_selector = f'#copilot-thread-list button[data-chat-thread="{first_thread_id}"]'
    second_selector = f'#copilot-thread-list button[data-chat-thread="{second_thread_id}"]'
    console.locator(first_selector).click()
    expect(console.locator(first_selector)).to_have_class("active")
    expect(console.locator(second_selector)).not_to_have_class("active")
