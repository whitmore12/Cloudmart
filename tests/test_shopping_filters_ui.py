"""Browser tests for the marketplace filters and sorting.

Scope:    category pills, New / Used pills, price sort, Clear, the fit and size
          line on a card, and the look of the pills. Loads the real index.html
          in headless Chromium with a fixed set of eight fake listings.
Run:      pytest tests/test_shopping_filters_ui.py   (see ui_helpers.py for setup)
Style:    prices and titles are asserted against exact expected lists, never
          against "looks sorted", so a text sort cannot sneak through.

Author: Claude (Anthropic)
"""

import json
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from ui_helpers import fake_backend, item, launch, sign_in, start_server  # noqa: E402

LISTINGS = [
    item(9, "Baggy wide leg jeans", 24.0, "Clothing", "Used", "makaila", "M", "Women's"),
    item(8, "Platform sneakers", 45.5, "Shoes", "New", "pam", "US 8", "Women's"),
    item(7, "Very Expensive", 10000.0, "Books", "New", "vaughn"),
    item(6, "Caterpillar book", 789.0, "Books", "New", "pam"),
    item(5, "Grandma's TV", 507.0, "Electronics", "Used", "pam"),
    item(4, "Mini fridge", 60.0, "Appliances", "Used", "tj"),
    item(3, "Desk lamp", 12.0, "Dorm & Home", "New", "tj"),
    item(2, "Fancy laptop", 2300.0, "Electronics", "New", "vaughn"),
]

@pytest.fixture(scope="module")
def site():
    """Serve the Frontend folder once for the whole module."""
    server, address = start_server()
    yield address
    server.shutdown()

@pytest.fixture(scope="module")
def browser():
    """One headless browser shared by the whole module."""
    with sync_playwright() as p:
        b = launch(p)
        yield b
        b.close()

@pytest.fixture
def page(browser, site):
    """A fresh page per test with a fake backend and a signed-in user. Any JavaScript error fails the test."""
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    fake_backend(pg)
    pg.route(re.compile(r".*/api/listings$"),
             lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(LISTINGS)))
    sign_in(pg)
    pg.goto(site + "/index.html")
    pg.wait_for_selector("#listings article")
    yield pg
    assert pg.errors == []
    pg.close()

def titles(page):
    """The titles on the page in the order they show."""
    return page.eval_on_selector_all("#listings article h3", "els => els.map(e => e.innerText)")

def prices(page):
    """Return the displayed prices as numbers, in page order."""
    return page.eval_on_selector_all("#listings .price", "els => els.map(e => parseFloat(e.innerText.replace('$','').replace(',','')))")

def click(page, words):
    """Click a filter pill by its visible text."""
    page.click("label.pill:has-text('%s')" % words)
    page.wait_for_timeout(150)

def test_all_listings_show_newest_first(page):
    """Scenario: Open the marketplace.

    Expected: All 8 listings show, newest first, count says 8 items.
    """
    assert len(titles(page)) == 8
    assert titles(page)[0] == "Baggy wide leg jeans"
    assert page.inner_text("#resultCount") == "8 items"

def test_there_are_ten_category_pills(page):
    """Scenario: Look at the category pills.

    Expected: There are 10.
    """
    assert page.locator("input[name=category]").count() == 10

def test_one_category_pill_filters(page):
    """Scenario: Click the Shoes pill.

    Expected: Only the sneakers show, count says 1 item.
    """
    click(page, "Shoes")
    assert titles(page) == ["Platform sneakers"]
    assert page.inner_text("#resultCount") == "1 item"

def test_two_category_pills_show_both(page):
    """Scenario: Click Books, then Electronics.

    Expected: Listings from both categories show.
    """
    click(page, "Books")
    click(page, "Electronics")
    assert sorted(titles(page)) == ["Caterpillar book", "Fancy laptop", "Grandma's TV", "Very Expensive"]

def test_turning_a_pill_off_brings_the_rest_back(page):
    """Scenario: Click Shoes twice.

    Expected: Pill turns off and all 8 come back.
    """
    click(page, "Shoes")
    click(page, "Shoes")
    assert len(titles(page)) == 8

def test_new_pill_only_shows_new_items(page):
    """Scenario: Click New.

    Expected: Only new items show.
    """
    click(page, "New")
    assert len(titles(page)) == 5
    assert "Grandma's TV" not in titles(page)

def test_used_pill_only_shows_used_items(page):
    """Scenario: Click Used.

    Expected: Only used items show.
    """
    click(page, "Used")
    assert sorted(titles(page)) == ["Baggy wide leg jeans", "Grandma's TV", "Mini fridge"]

def test_category_and_condition_work_together(page):
    """Scenario: Click Books, Electronics and Used.

    Expected: Only the used electronics item shows.
    """
    click(page, "Books")
    click(page, "Electronics")
    click(page, "Used")
    assert titles(page) == ["Grandma's TV"]

def test_a_filter_with_no_matches_shows_nothing(page):
    """Scenario: Click a category with no listings.

    Expected: Nothing shows, count says 0 items.
    """
    click(page, "Beauty")
    assert titles(page) == []
    assert page.inner_text("#resultCount") == "0 items"

def test_price_low_to_high(page):
    """Scenario: Sort by price low to high.

    Expected: Prices go up from the cheapest.
    """
    page.select_option("#sortSelect", "low")
    page.wait_for_timeout(150)
    assert prices(page) == sorted(prices(page))
    assert titles(page)[0] == "Desk lamp"

def test_price_high_to_low(page):
    """Scenario: Sort by price high to low.

    Expected: Prices go down from the most expensive.
    """
    page.select_option("#sortSelect", "high")
    page.wait_for_timeout(150)
    assert prices(page) == sorted(prices(page), reverse=True)
    assert titles(page)[0] == "Very Expensive"

def test_sort_still_works_after_filtering(page):
    """Scenario: Click Used, then sort high to low.

    Expected: The sort works on the filtered list.
    """
    click(page, "Used")
    page.select_option("#sortSelect", "high")
    page.wait_for_timeout(150)
    assert titles(page) == ["Grandma's TV", "Mini fridge", "Baggy wide leg jeans"]

def test_sorting_back_to_newest_goes_by_id(page):
    """Scenario: Sort low, then back to newest.

    Expected: Goes back to newest first.
    """
    page.select_option("#sortSelect", "low")
    page.select_option("#sortSelect", "newest")
    page.wait_for_timeout(150)
    assert titles(page)[0] == "Baggy wide leg jeans"

def test_clear_resets_everything(page):
    """Scenario: Pick pills and a sort, then click Clear.

    Expected: All 8 show, pills are off, sort is back to Newest.
    """
    click(page, "Books")
    click(page, "Used")
    page.select_option("#sortSelect", "high")
    page.click("text=Clear")
    page.wait_for_timeout(150)
    assert len(titles(page)) == 8
    assert page.locator("input[name=category]:checked").count() == 0
    assert page.locator("input[name=condition]:checked").count() == 0
    assert page.input_value("#sortSelect") == "newest"

def test_clothing_and_shoes_show_fit_and_size(page):
    """Scenario: Look at clothing and shoes listings.

    Expected: Fit and size show on the card.
    """
    text = page.inner_text("#listings")
    assert "Women's" in text and "US 8" in text

def test_other_categories_show_no_size_line(page):
    """Scenario: Look at a Books listing.

    Expected: No size line shows.
    """
    click(page, "Books")
    assert "Women's" not in page.inner_text("#listings")
    assert "US " not in page.inner_text("#listings")

def test_search_and_pills_work_together(page):
    """Scenario: Click Electronics and search laptop.

    Expected: Pills and search work together.
    """
    click(page, "Electronics")
    page.fill("#searchInput", "laptop")
    page.dispatch_event("#searchInput", "keyup")
    page.wait_for_timeout(150)
    assert titles(page) == ["Fancy laptop"]

# --- Pill appearance ---

def test_no_pill_has_an_emoji(page):
    """Scenario: Read the text of all 12 pills.

    Expected: No emojis, plain text only.
    """
    words = page.eval_on_selector_all("label.pill", "els => els.map(e => e.innerText)")
    assert len(words) == 12
    for word in words:
        assert word.isascii(), "pill has a non letter character: %s" % word

def test_every_pill_looks_the_same(page):
    """Scenario: Compare the size, font and spacing of every pill.

    Expected: They all look exactly the same.
    """
    looks = page.eval_on_selector_all(
        "label.pill",
        "els => els.map(e => { const s = getComputedStyle(e); return [s.fontSize, s.fontFamily, s.borderRadius, s.paddingTop, s.paddingLeft, s.height].join('|') })")
    assert len(set(looks)) == 1

def test_hearting_an_item_keeps_the_filters_and_sort(page):
    """Scenario: Pick pills and a sort, then heart an item.

    Expected: The pills and sort stay the way they were.
    """
    click(page, "Books")
    click(page, "Electronics")
    page.select_option("#sortSelect", "low")
    page.wait_for_timeout(150)
    page.click("#listings article:first-child .heart-btn")
    page.wait_for_timeout(400)
    assert page.locator("input[name=category]:checked").count() == 2
    assert page.input_value("#sortSelect") == "low"
