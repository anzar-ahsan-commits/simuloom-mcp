"""Covers Copilot conversation selection: creating and selecting a thread does not require the
optional local AI to be enabled or reachable, so this runs without any external AI dependency."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_create_and_select_copilot_conversation(console: Page, seeded_simulation: dict):
    console.click('.nav-item[data-view="copilot"]')
    expect(console.locator("#copilot-ai-status")).to_be_visible()

    console.select_option("#copilot-simulation", seeded_simulation["id"])
    console.click("#new-chat-button")

    thread_buttons = console.locator("#copilot-thread-list button[data-chat-thread]")
    active_thread = console.locator("#copilot-thread-list button[data-chat-thread].active")
    expect(active_thread).to_have_count(1)
    expect(console.locator("#copilot-title")).to_contain_text(seeded_simulation["name"])
    expect(console.locator("#copilot-input")).to_be_focused()
    first_thread_id = active_thread.get_attribute("data-chat-thread")
    # seeded_simulation is session-scoped, so another test may already have created a
    # conversation against it (e.g. the accessibility suite's copilot view check runs first
    # alphabetically and does its own "New chat" click). Count relative to this now-settled
    # state (the expect() calls above only pass once the first creation has fully rendered)
    # rather than asserting an absolute total.
    count_after_first_create = thread_buttons.count()

    console.click("#new-chat-button")
    new_active_thread = console.locator("#copilot-thread-list button[data-chat-thread].active")
    # A to_have_count-only check here can be satisfied by state left over from the *first*
    # thread's creation before the second createCopilotThread() call has progressed far enough
    # to render its own thread as active. Waiting for the active thread's id to actually change
    # is what forces a real wait for the second creation to finish, rather than reading stale
    # state that happens to already match.
    expect(new_active_thread).not_to_have_attribute("data-chat-thread", first_thread_id)
    expect(thread_buttons).to_have_count(count_after_first_create + 1)
    expect(new_active_thread).to_have_count(1)
    second_thread_id = new_active_thread.get_attribute("data-chat-thread")
    assert second_thread_id != first_thread_id

    # Selecting the first conversation again makes it the active one instead.
    first_selector = f'#copilot-thread-list button[data-chat-thread="{first_thread_id}"]'
    second_selector = f'#copilot-thread-list button[data-chat-thread="{second_thread_id}"]'
    console.locator(first_selector).click()
    expect(console.locator(first_selector)).to_have_class("active")
    expect(console.locator(second_selector)).not_to_have_class("active")
