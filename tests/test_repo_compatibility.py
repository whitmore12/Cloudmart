"""Compatibility tests: does the new work still fit the rest of the repo?

Groups:   1. Front end and back end agree on categories, conditions, fits, sizes.
          2. The routes the team depends on are still registered.
          3. Old data and the live-site startup path still work (needs the database).
          4. The main pages open in a browser without a JavaScript error.
Run:      CLOUDMART_TEST_DSN="host=127.0.0.1 port=5433 dbname=cloudmart_test user=postgres" pytest tests/test_repo_compatibility.py
          Groups 1 and 2 need no database. Groups 3 and 4 skip themselves
          when their requirements are missing.
Note:     admin pages are left out of group 4 because they need real admin data.

Author: Claude (Anthropic)
"""

import json
import os
import re
import sys

import psycopg
import pytest

for key, value in {"AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
                   "BUCKET_NAME": "x", "ADMIN_BOOTSTRAP_TOKEN": "x"}.items():
    os.environ.setdefault(key, value)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import application as appmod  # noqa: E402
from db_helpers import reset_database  # noqa: E402
from ui_helpers import FRONTEND, fake_backend, launch, sign_in, start_server  # noqa: E402

DSN = os.getenv("CLOUDMART_TEST_DSN")
needs_database = pytest.mark.skipif(not DSN or "test" not in DSN.lower(),
                                   reason="set CLOUDMART_TEST_DSN to a throwaway database with test in its name")

def read_frontend(name):
    """Return the text of one page in the Frontend folder."""
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()

def unescape_html(text):
    """Turn the &amp; entity into a plain ampersand."""
    return text.replace("&amp;", "&")

# --- Front end and back end agree ---

def test_marketplace_pills_match_the_categories_the_server_allows():
    """Scenario: Compare the marketplace pills with the categories the server allows.

    Expected: Same 10 names in the same order.
    """
    pills = re.findall(r'name="category" value="([^"]+)"', read_frontend("index.html"))
    assert [unescape_html(p) for p in pills] == appmod.ALLOWED_CATEGORIES

def test_sell_page_categories_match_the_categories_the_server_allows():
    """Scenario: Compare the sell page categories with the server.

    Expected: Same 10 names in the same order.
    """
    block = re.search(r'<select id="category".*?</select>', read_frontend("create.html"), re.S).group(0)
    options = re.findall(r"<option>([^<]+)</option>", block)
    assert [unescape_html(o) for o in options] == appmod.ALLOWED_CATEGORIES

def test_condition_choices_match_on_the_pills_the_sell_page_and_the_server():
    """Scenario: Compare New and Used on the pills, the sell page and the server.

    Expected: All three agree.
    """
    pills = re.findall(r'name="condition" value="([^"]+)"', read_frontend("index.html"))
    block = re.search(r'<select id="condition".*?</select>', read_frontend("create.html"), re.S).group(0)
    options = re.findall(r"<option>([^<]+)</option>", block)
    assert pills == options == appmod.ALLOWED_CONDITIONS

def test_fit_choices_match_on_the_sell_page_and_the_server():
    """Scenario: Compare the fit choices on the sell page with the server.

    Expected: They agree.
    """
    block = re.search(r'<select id="fit".*?</select>', read_frontend("create.html"), re.S).group(0)
    options = [o.replace("&#39;", "'") for o in re.findall(r"<option>([^<]+)</option>", block)]
    assert options == appmod.ALLOWED_FITS

def test_size_lists_match_on_the_sell_page_and_the_server():
    """Scenario: Compare the size lists on the sell page with the server.

    Expected: They agree.
    """
    page = read_frontend("create.html")
    clothing = json.loads(re.search(r"CLOTHING_SIZES = (\[.*?\]);", page).group(1))
    assert clothing == appmod.SIZES_BY_CATEGORY["Clothing"]
    assert "length: 15" in page
    assert len(appmod.SIZES_BY_CATEGORY["Shoes"]) == 15

# --- Routes the team depends on ---

ROUTES = [
    ("/api/auth/login", "POST"), ("/api/auth/register", "POST"),
    ("/api/listings", "GET"), ("/api/listings", "POST"),
    ("/api/listings/<int:listing_id>", "GET"), ("/api/listings/<int:listing_id>", "PUT"),
    ("/api/listings/<int:listing_id>", "DELETE"),
    ("/api/listings/<int:listing_id>/initiate-purchase", "POST"),
    ("/api/listings/<int:listing_id>/confirm-purchase", "POST"),
    ("/api/listings/<int:listing_id>/get-pin", "GET"),
    ("/api/listings/<int:listing_id>/admin-bypass-pin", "POST"),
    ("/api/listings/<int:listing_id>/mark-active", "PUT"),
    ("/api/listings/pending", "GET"), ("/api/listings/by-seller/<username>", "GET"),
    ("/api/wishlist", "GET"), ("/api/wishlist", "POST"),
    ("/api/wallet/balance", "GET"), ("/api/wallet/history", "GET"),
    ("/api/returns/request", "POST"), ("/api/messages", "POST"),
]

def test_team_routes_are_still_registered():
    """Scenario: Check 20 routes the team uses, like login, wallet, wishlist and returns.

    Expected: Every one is still registered, so nothing was lost in a merge.
    """
    have = {(r.rule, m) for r in appmod.app.url_map.iter_rules() for m in r.methods}
    missing = [(path, method) for path, method in ROUTES if (path, method) not in have]
    assert missing == []

# --- Old data and startup ---

@pytest.fixture
def database(monkeypatch):
    """Point the app at the throwaway database and rebuild its tables."""
    monkeypatch.setattr(appmod, "get_db_connection", lambda: psycopg.connect(DSN))
    reset_database(DSN)
    appmod.init_db()
    appmod.app.config["TESTING"] = True
    conn = psycopg.connect(DSN)
    conn.execute("TRUNCATE transactions, return_requests, wishlist, listings, users RESTART IDENTITY CASCADE")
    conn.commit()
    conn.close()
    return appmod.app.test_client()

def run(sql, args=()):
    """Run one write statement on the test database and commit it."""
    conn = psycopg.connect(DSN)
    conn.execute(sql, args)
    conn.commit()
    conn.close()

def query(sql, args=()):
    """Run a SELECT on the test database and return every row."""
    conn = psycopg.connect(DSN)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows

@needs_database
def test_setting_up_the_tables_twice_is_fine(database):
    """Scenario: Set up the tables two times in a row, like the live site does when it starts.

    Expected: No error and size and fit are only added once.
    """
    # The live site runs init_db on every start.
    appmod.init_db()
    appmod.init_db()
    columns = [r[0] for r in query("SELECT column_name FROM information_schema.columns WHERE table_name = 'listings'")]
    assert columns.count("size") == 1 and columns.count("fit") == 1

@needs_database
def test_size_and_fit_columns_are_allowed_to_be_empty(database):
    """Scenario: Look at the size and fit columns.

    Expected: Both are allowed to be empty.
    """
    rows = query("SELECT column_name, is_nullable FROM information_schema.columns "
                 "WHERE table_name = 'listings' AND column_name IN ('size', 'fit')")
    assert sorted(rows) == [("fit", "YES"), ("size", "YES")]

@needs_database
def test_old_listing_without_category_size_or_fit_still_loads(database):
    """Scenario: Load an old listing that has no category, size or fit.

    Expected: It loads and size and fit are empty.
    """
    run("INSERT INTO users (email, username, password_hash) VALUES ('old@my.hamptonu.edu', 'old', 'x')")
    run("INSERT INTO listings (user_id, title, price, image, seller, status) VALUES (1, 'Old thing', 5, 'img', 'old', 'active')")
    res = database.get("/api/listings")
    assert res.status_code == 200
    old = [i for i in res.get_json() if i["title"] == "Old thing"][0]
    assert old["size"] is None and old["fit"] is None

@needs_database
def test_old_listing_can_still_be_bought(database):
    """Scenario: Buy an old listing.

    Expected: The purchase goes through.
    """
    run("INSERT INTO users (email, username, password_hash, pirate_dollars) VALUES ('old@my.hamptonu.edu', 'old', 'x', 0), ('b@my.hamptonu.edu', 'b', 'x', 100)")
    run("INSERT INTO listings (user_id, title, price, image, seller, status) VALUES (1, 'Old thing', 5, 'img', 'old', 'active')")
    res = database.post("/api/listings/1/initiate-purchase", json={"user_id": 2, "role": "user"})
    assert res.status_code == 200

@needs_database
def test_register_then_login_still_works(database):
    """Scenario: Register, then log in.

    Expected: Both work.
    """
    reg = database.post("/api/auth/register", json={"email": "new@my.hamptonu.edu", "username": "newbie", "password": "password123"})
    assert reg.status_code in (200, 201)
    login = database.post("/api/auth/login", json={"username": "newbie", "password": "password123"})
    assert login.status_code == 200

@needs_database
def test_wrong_password_is_still_a_401(database):
    """Scenario: Log in with the wrong password.

    Expected: Still a 401.
    """
    database.post("/api/auth/register", json={"email": "new@my.hamptonu.edu", "username": "newbie", "password": "password123"})
    assert database.post("/api/auth/login", json={"username": "newbie", "password": "nope"}).status_code == 401

@needs_database
def test_by_seller_listing_page_still_works_with_the_new_columns(database):
    """Scenario: Load a seller's listings after posting a new clothing item.

    Expected: The page loads with the new item.
    """
    run("INSERT INTO users (email, username, password_hash) VALUES ('s@my.hamptonu.edu', 'sally', 'x')")
    database.post("/api/listings", json={"user_id": 1, "title": "Jeans", "price": 20, "category": "Clothing",
                                         "condition": "Used", "size": "M", "fit": "Women's"})
    res = database.get("/api/listings/by-seller/sally")
    assert res.status_code == 200
    assert [i["title"] for i in res.get_json()] == ["Jeans"]

@needs_database
def test_wallet_transfer_still_moves_money_next_to_the_purchase_flow(database):
    """Scenario: Transfer money in the wallet.

    Expected: The money moves.
    """
    run("INSERT INTO users (email, username, password_hash, pirate_dollars) VALUES ('a@my.hamptonu.edu', 'a', 'x', 100), ('b@my.hamptonu.edu', 'b', 'x', 100)")
    res = database.post("/api/wallet/transfer", json={"buyer_id": 1, "seller_id": 2, "amount": 10})
    assert res.status_code == 200
    assert query("SELECT pirate_dollars FROM users ORDER BY id") == [(90,), (110,)]

@needs_database
def test_wallet_transfer_still_refuses_when_there_is_not_enough_money(database):
    """Scenario: Transfer more money than the buyer has.

    Expected: Refused and nobody's money changes.
    """
    run("INSERT INTO users (email, username, password_hash, pirate_dollars) VALUES ('a@my.hamptonu.edu', 'a', 'x', 5), ('b@my.hamptonu.edu', 'b', 'x', 100)")
    res = database.post("/api/wallet/transfer", json={"buyer_id": 1, "seller_id": 2, "amount": 10})
    assert res.status_code == 400
    assert query("SELECT pirate_dollars FROM users ORDER BY id") == [(5,), (100,)]

# --- Main pages load cleanly ---

# Admin pages need real admin data from the server, so they are excluded.
PAGES = sorted(f for f in os.listdir(FRONTEND) if f.endswith(".html") and not f.startswith("admin"))

@pytest.fixture(scope="module")
def site():
    """Serve the Frontend folder once for the whole module."""
    server, address = start_server()
    yield address
    server.shutdown()

@pytest.fixture(scope="module")
def browser():
    """One headless browser shared by the whole module."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = launch(p)
        yield b
        b.close()

def test_every_page_opens_without_a_javascript_error(browser, site):
    """Scenario: Open the main pages in a browser with a fake server.

    Expected: No page has a JavaScript error.
    """
    broken = {}
    for name in PAGES:
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        fake_backend(page)
        page.route(re.compile(r".*/api/listings$"), lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
        sign_in(page)
        page.goto(site + "/" + name)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        page.close()
        if errors:
            broken[name] = errors
    assert broken == {}
    assert len(PAGES) >= 7
