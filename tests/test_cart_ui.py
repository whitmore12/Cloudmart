"""Browser tests for the cart page when an item was bought by someone else.

Scope:    the cleanup when the cart opens, and the checkout messages. The server
          is faked per test, so each test chooses what it answers for every item.
Run:      pytest tests/test_cart_ui.py   (see ui_helpers.py for setup)

Author: Claude (Anthropic)
"""

import json
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from ui_helpers import fake_backend, item, launch, sign_in, start_server  # noqa: E402

GONE = {"error": "Listing is not available for purchase"}

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

def pin(number):
    """Build the (status, body) pair the server returns when a purchase succeeds."""
    return (200, {"success": True, "verification_pin": number, "pin_expires_at": "2026-11-14T12:00:00", "status": "pending"})

def open_cart(browser, site, cart, statuses=None, buy_answers=None, check_fails=False):
    """Open the cart page with the given items.

    statuses:    {listing_id: status} for what the server reports on page load.
                 Ids that are not listed are active; "missing" answers 404.
    buy_answers: {listing_id: (http_status, body)} for what checkout gets back.
    check_fails: abort the status lookups to simulate the server being down.
    """
    statuses = statuses or {}
    buy_answers = buy_answers or {}
    page = browser.new_page()
    page.errors = []
    page.dialogs = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("dialog", lambda d: (page.dialogs.append(d.message), d.accept()))
    fake_backend(page)

    def status(route):
        if check_fails:
            return route.abort()
        listing_id = int(route.request.url.rsplit("/", 1)[1])
        s = statuses.get(listing_id, "active")
        if s == "missing":
            return route.fulfill(status=404, content_type="application/json", body='{"error":"Listing not found"}')
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"id": listing_id, "status": s}))
    page.route(re.compile(r".*/api/listings/\d+$"), status)

    def buy(route):
        listing_id = int(route.request.url.split("/api/listings/")[1].split("/")[0])
        code, body = buy_answers.get(listing_id, pin("0000"))
        route.fulfill(status=code, content_type="application/json", body=json.dumps(body))
    page.route(re.compile(r".*/initiate-purchase$"), buy)

    sign_in(page, cart)
    page.goto(site + "/cart.html")
    page.wait_for_timeout(1200)
    return page

def cart_ids(page):
    """Return the ids of the items left in the browser's cart."""
    return [i["id"] for i in json.loads(page.evaluate("localStorage.getItem('cart')"))]

def checkout(page):
    page.click("text=Checkout")
    page.wait_for_timeout(1500)

def test_item_sold_while_away_is_taken_out_when_the_cart_opens(browser, site):
    """Scenario: Open the cart with items that sold while the buyer was away.

    Expected: They are removed and a notice names them.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24), item(2, "Sneakers", 45), item(3, "Novel", 8)],
                    statuses={2: "sold", 3: "missing"})
    notice = page.inner_text("#cartNotice")
    assert "Sneakers" in notice and "Novel" in notice
    assert "no longer available" in notice
    assert cart_ids(page) == [1]
    page.close()

def test_cart_only_shows_and_counts_what_is_still_available(browser, site):
    """Scenario: The cart opens with items that sold while the buyer was away, then the table and subtotal are read.

    Expected: Only available items show and are counted.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24), item(2, "Sneakers", 45)], statuses={2: "sold"})
    assert "Hoodie" in page.inner_text("#cartItems")
    assert "Sneakers" not in page.inner_text("#cartItems")
    assert page.inner_text("#cartTotal").strip() == "$24.00"
    page.close()

def test_a_pending_item_counts_as_gone(browser, site):
    """Scenario: Open the cart with an item that is pending.

    Expected: It counts as gone and is removed.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24)], statuses={1: "pending"})
    assert cart_ids(page) == []
    assert "Hoodie" in page.inner_text("#cartNotice")
    page.close()

def test_only_item_gone_shows_the_empty_cart_and_the_notice(browser, site):
    """Scenario: Only item in the cart is gone.

    Expected: The empty cart shows with the notice, worded for one item.
    """
    page = open_cart(browser, site, [item(2, "Sneakers", 45)], statuses={2: "sold"})
    assert page.is_visible("#emptyState")
    assert page.is_visible("#cartNotice")
    assert page.inner_text("#cartNotice").startswith("This item is")
    page.close()

def test_nothing_gone_means_no_notice(browser, site):
    """Scenario: Nothing is gone.

    Expected: No notice and the cart is unchanged.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24)])
    assert not page.is_visible("#cartNotice")
    assert cart_ids(page) == [1]
    page.close()

def test_if_the_check_fails_the_cart_is_left_alone(browser, site):
    """Scenario: The server check fails.

    Expected: Cart is left alone, no notice, no page error.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24), item(2, "Sneakers", 45)], check_fails=True)
    assert cart_ids(page) == [1, 2]
    assert not page.is_visible("#cartNotice")
    assert page.errors == []
    page.close()

def test_checkout_skips_the_lost_item_and_keeps_the_pins(browser, site):
    """Scenario: Checkout with one lost item and two good ones.

    Expected: One message with both PINs and the lost item named, cart is emptied.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24), item(2, "Sneakers", 45), item(3, "Novel", 8)],
                    buy_answers={1: pin("1111"), 2: (409, GONE), 3: pin("3333")})
    checkout(page)
    message = page.dialogs[0]
    assert "1111" in message and "3333" in message
    assert "Sneakers" in message and "taken out of your cart" in message
    assert cart_ids(page) == []
    assert "profile.html" in page.url
    assert page.errors == []
    page.close()

def test_checkout_with_only_lost_items_stays_on_the_cart(browser, site):
    """Scenario: Checkout where every item was lost.

    Expected: Tells the buyer, no "Checkout complete", stays on the cart page.
    """
    page = open_cart(browser, site, [item(2, "Sneakers", 45)], buy_answers={2: (409, GONE)})
    checkout(page)
    assert "Sneakers" in page.dialogs[0]
    assert "Checkout complete" not in page.dialogs[0]
    assert "cart.html" in page.url
    assert cart_ids(page) == []
    assert page.is_visible("#emptyState")
    page.close()

def test_a_real_error_keeps_the_item_so_they_can_try_again(browser, site):
    """Scenario: Checkout where one item fails with a real error.

    Expected: The bought item leaves, the failed one stays so they can retry, PIN is kept.
    """
    page = open_cart(browser, site, [item(1, "Hoodie", 24), item(2, "Laptop", 5000), item(3, "Novel", 8)],
                    buy_answers={1: pin("1111"), 2: (400, {"error": "Insufficient funds"}), 3: pin("3333")})
    checkout(page)
    message = page.dialogs[0]
    assert "1111" in message
    assert "Insufficient funds" in message
    # The purchased item leaves the cart; the one that failed and the one after it stay.
    assert cart_ids(page) == [2, 3]
    page.close()
