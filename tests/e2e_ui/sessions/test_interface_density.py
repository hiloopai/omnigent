"""E2E coverage for live and reload-persistent interface density."""

from __future__ import annotations

from playwright.sync_api import Page, expect

STORAGE_KEY = "omnigent:interface-density"


def _root_density(page: Page) -> str | None:
    return page.locator("html").get_attribute("data-density")


def _sidebar_row_padding(page: Page) -> str:
    return page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--density-sidebar-row-padding-y').trim()"
    )


def test_interface_density_applies_live_and_survives_reload(
    page: Page, seeded_session: tuple[str, str]
) -> None:
    base_url, _session_id = seeded_session
    page.goto(f"{base_url}/settings/appearance")
    group = page.get_by_role("radiogroup", name="Interface density")
    expect(group).to_be_visible(timeout=30_000)

    assert _root_density(page) == "comfortable"
    assert _sidebar_row_padding(page) == "0.5rem"
    assert page.evaluate(f"() => localStorage.getItem('{STORAGE_KEY}')") is None

    page.get_by_test_id("density-compact").click()
    expect(page.get_by_test_id("density-compact")).to_have_attribute("aria-checked", "true")
    assert _root_density(page) == "compact"
    assert _sidebar_row_padding(page) == "0.25rem"

    page.get_by_test_id("density-spacious").click()
    expect(page.get_by_test_id("density-spacious")).to_have_attribute("aria-checked", "true")
    assert _root_density(page) == "spacious"
    assert _sidebar_row_padding(page) == "0.75rem"
    assert page.evaluate(f"() => localStorage.getItem('{STORAGE_KEY}')") == "spacious"

    page.reload()
    expect(group).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("density-spacious")).to_have_attribute("aria-checked", "true")
    assert _root_density(page) == "spacious"
    assert _sidebar_row_padding(page) == "0.75rem"

    page.get_by_test_id("density-reset").click()
    expect(page.get_by_test_id("density-comfortable")).to_have_attribute("aria-checked", "true")
    assert _root_density(page) == "comfortable"
    assert page.evaluate(f"() => localStorage.getItem('{STORAGE_KEY}')") is None
