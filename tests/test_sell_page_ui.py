"""Browser tests for the fit and size dropdowns on the create-listing page.

Scope:    when the dropdowns appear, what they offer, what is posted to the
          server on create and on edit. Loads the real create.html in headless
          Chromium and intercepts the API calls, so nothing is saved anywhere.
Run:      pytest tests/test_sell_page_ui.py   (see ui_helpers.py for setup)

Author: Claude (Anthropic)
"""

import json
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from ui_helpers import fake_backend, launch, sign_in, start_server  # noqa: E402

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
    pg = browser.new_page()
    pg.errors = []
    pg.dialogs = []
    pg.posted = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("dialog", lambda d: (pg.dialogs.append(d.message), d.accept()))
    fake_backend(pg)

    def listings(route):
        if route.request.method in ("POST", "PUT"):
            pg.posted.append((route.request.method, json.loads(route.request.post_data)))
            return route.fulfill(status=201, content_type="application/json", body='{"id": 99}')
        route.fulfill(status=200, content_type="application/json", body="[]")
    pg.route(re.compile(r".*/api/listings$"), listings)
    sign_in(pg)
    pg.goto(site + "/create.html")
    yield pg
    assert pg.errors == []
    pg.close()

def fill(page, category, condition="New"):
    """Fill in the fields every listing needs, leaving size and fit to the test."""
    page.fill("#title", "Test item")
    page.fill("#price", "20.50")
    page.select_option("#category", category)
    page.select_option("#condition", condition)

def submit(page):
    """Press the create button and give the page a moment to react."""
    page.click("#submitBtn")
    page.wait_for_timeout(600)

def test_fit_and_size_start_hidden(page):
    """Scenario: Open the create listing page.

    Expected: Fit and size are hidden.
    """
    assert not page.is_visible("#sizeFields")

def test_clothing_shows_fit_and_the_clothing_sizes(page):
    """Scenario: Pick Clothing.

    Expected: Fit and size show, with sizes XS, S, M, L, XL and XXL.
    """
    page.select_option("#category", "Clothing")
    assert page.is_visible("#sizeFields")
    sizes = page.eval_on_selector_all("#size option:not([disabled])", "els => els.map(e => e.innerText)")
    assert sizes == ["XS", "S", "M", "L", "XL", "XXL"]

def test_shoes_show_us_sizes_one_to_fifteen(page):
    """Scenario: Pick Shoes.

    Expected: Sizes are US 1 through US 15.
    """
    page.select_option("#category", "Shoes")
    sizes = page.eval_on_selector_all("#size option:not([disabled])", "els => els.map(e => e.innerText)")
    assert sizes == ["US %s" % n for n in range(1, 16)]

def test_other_categories_hide_fit_and_size_again(page):
    """Scenario: Pick Clothing, then Books.

    Expected: Fit and size hide again and are cleared.
    """
    page.select_option("#category", "Clothing")
    page.select_option("#fit", "Men's")
    page.select_option("#category", "Books")
    assert not page.is_visible("#sizeFields")
    assert page.input_value("#fit") == ""

def test_switching_from_clothing_to_shoes_swaps_the_size_list(page):
    """Scenario: Pick a clothing size, then switch to Shoes.

    Expected: The size list swaps and the old size is cleared.
    """
    page.select_option("#category", "Clothing")
    page.select_option("#size", "M")
    page.select_option("#category", "Shoes")
    assert page.input_value("#size") == ""
    assert page.locator("#size option:not([disabled])").count() == 15

def test_clothing_without_fit_and_size_is_not_sent(page):
    """Scenario: Create clothing with no fit or size.

    Expected: Warned, and nothing is sent to the server.
    """
    fill(page, "Clothing")
    submit(page)
    assert "Please pick a fit and a size." in page.dialogs[0]
    assert page.posted == []

def test_clothing_listing_sends_size_fit_and_the_rest(page):
    """Scenario: Create a clothing listing.

    Expected: The server gets category, condition, size, fit, title and price.
    """
    fill(page, "Clothing", "Used")
    page.select_option("#fit", "Women's")
    page.select_option("#size", "M")
    submit(page)
    method, body = page.posted[0]
    assert method == "POST"
    assert body["category"] == "Clothing" and body["condition"] == "Used"
    assert body["size"] == "M" and body["fit"] == "Women's"
    assert body["price"] == 20.5 and body["title"] == "Test item"

def test_shoe_listing_sends_a_shoe_size(page):
    """Scenario: Create a shoe listing.

    Expected: The server gets the shoe size.
    """
    fill(page, "Shoes")
    page.select_option("#fit", "Unisex")
    page.select_option("#size", "US 9")
    submit(page)
    assert page.posted[0][1]["size"] == "US 9"

def test_books_listing_sends_no_size_or_fit(page):
    """Scenario: Create a Books listing.

    Expected: The server gets empty size and fit.
    """
    fill(page, "Books")
    submit(page)
    body = page.posted[0][1]
    assert body["category"] == "Books"
    assert body["size"] is None and body["fit"] is None

def test_missing_category_or_condition_is_not_sent(page):
    """Scenario: Create with no category or condition.

    Expected: Warned, and nothing is sent.
    """
    page.fill("#title", "Test item")
    page.fill("#price", "5")
    submit(page)
    assert "Please pick a category and a condition." in page.dialogs[0]
    assert page.posted == []

def test_successful_create_goes_back_to_the_marketplace(page):
    """Scenario: Create a listing successfully.

    Expected: Shows the success message and goes to the marketplace.
    """
    fill(page, "Books")
    submit(page)
    assert "Listing created successfully!" in page.dialogs[0]
    assert "index.html" in page.url

def test_editing_a_clothing_listing_fills_in_size_and_fit(browser, site):
    """Scenario: Open a clothing listing to edit.

    Expected: Category, fit and size are filled in.
    """
    page = browser.new_page()
    fake_backend(page)
    saved = {"id": 5, "title": "Jeans", "price": 30, "category": "Clothing", "condition": "Used",
             "image": "x", "size": "L", "fit": "Men's"}
    page.route(re.compile(r".*/api/listings/5$"),
               lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(saved)))
    sign_in(page)
    page.goto(site + "/create.html?edit=5")
    page.wait_for_timeout(800)
    assert page.is_visible("#sizeFields")
    assert page.input_value("#fit") == "Men's"
    assert page.input_value("#size") == "L"
    assert page.input_value("#category") == "Clothing"
    page.close()

def test_editing_a_listing_sends_a_put_with_the_new_size(browser, site):
    """Scenario: Change the size and update.

    Expected: The server gets a PUT with the new size and the old fit.
    """
    page = browser.new_page()
    page.dialogs = []
    posted = []
    page.on("dialog", lambda d: (page.dialogs.append(d.message), d.accept()))
    fake_backend(page)
    saved = {"id": 5, "title": "Jeans", "price": 30, "category": "Clothing", "condition": "Used",
             "image": "x", "size": "L", "fit": "Men's"}

    def one(route):
        if route.request.method == "PUT":
            posted.append(json.loads(route.request.post_data))
            return route.fulfill(status=200, content_type="application/json", body='{"success": true}')
        route.fulfill(status=200, content_type="application/json", body=json.dumps(saved))
    page.route(re.compile(r".*/api/listings/5$"), one)
    sign_in(page)
    page.goto(site + "/create.html?edit=5")
    page.wait_for_timeout(800)
    page.select_option("#size", "XL")
    page.click("#submitBtn")
    page.wait_for_timeout(600)
    assert posted[0]["size"] == "XL" and posted[0]["fit"] == "Men's"
    page.close()
