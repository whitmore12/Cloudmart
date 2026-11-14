"""Server-side tests for the shopping fields on a listing.

Scope:    category, condition, size and fit, through the real Flask routes
          (create, read, edit) against a throwaway PostgreSQL database.
Run:      CLOUDMART_TEST_DSN="host=127.0.0.1 port=5433 dbname=cloudmart_test user=postgres" pytest tests/test_shopping_fields.py
Safety:   the database is wiped before every test, so its name must contain
          "test". Without CLOUDMART_TEST_DSN the whole module is skipped.
Style:    every test is a single scenario with a docstring that states the
          scenario and the expected outcome.

Author: Claude (Anthropic)
"""

import os
import sys

import psycopg
import pytest

for key, value in {"AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
                   "BUCKET_NAME": "x", "ADMIN_BOOTSTRAP_TOKEN": "x"}.items():
    os.environ.setdefault(key, value)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import application as appmod  # noqa: E402
from db_helpers import reset_database  # noqa: E402

DSN = os.getenv("CLOUDMART_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN or "test" not in DSN.lower(),
                                reason="set CLOUDMART_TEST_DSN to a throwaway database with test in its name")

def run(sql, args=()):
    """Run one write statement on the test database and commit it."""
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    conn.close()

def query(sql, args=()):
    """Run a SELECT on the test database and return every row."""
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    conn.close()
    return rows

@pytest.fixture
def client(monkeypatch):
    """Flask test client on the throwaway database, with one seller already created."""
    monkeypatch.setattr(appmod, "get_db_connection", lambda: psycopg.connect(DSN))
    reset_database(DSN)
    appmod.init_db()
    run("TRUNCATE transactions, listings, users RESTART IDENTITY CASCADE")
    run("INSERT INTO users (email, username, password_hash) VALUES ('seller@my.hamptonu.edu', 'seller', 'x')")
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()

def seller_id():
    """Return the id of the seller created by the fixture."""
    return query("SELECT id FROM users WHERE username = 'seller'")[0][0]

def post(client, **changes):
    """POST a listing. A valid clothing listing is the default and keyword arguments override fields."""
    body = {"user_id": seller_id(), "title": "Test item", "price": 20, "category": "Clothing",
            "condition": "New", "size": "M", "fit": "Women's"}
    body.update(changes)
    return client.post("/api/listings", json=body)

def saved(listing_id):
    """Read category, condition, size and fit back from the database for a listing."""
    return query("SELECT category, condition, size, fit FROM listings WHERE id = %s", (listing_id,))[0]

def test_clothing_saves_size_and_fit(client):
    """Scenario: Post a clothing listing with size M and fit Women's.

    Expected: Saved with that size and fit.
    """
    res = post(client)
    assert res.status_code == 201
    assert saved(res.get_json()["id"]) == ("Clothing", "New", "M", "Women's")

def test_shoes_save_a_us_size(client):
    """Scenario: Post a shoes listing with size US 8.

    Expected: Saved with the shoe size and fit.
    """
    res = post(client, category="Shoes", size="US 8")
    assert res.status_code == 201
    assert saved(res.get_json()["id"])[2:] == ("US 8", "Women's")

def test_listing_comes_back_with_size_and_fit(client):
    """Scenario: Load the listings after posting clothing.

    Expected: The listing comes back with size, fit and category.
    """
    post(client, title="Baggy jeans", size="L", fit="Men's")
    items = client.get("/api/listings").get_json()
    jeans = [i for i in items if i["title"] == "Baggy jeans"][0]
    assert jeans["size"] == "L"
    assert jeans["fit"] == "Men's"
    assert jeans["category"] == "Clothing"

def test_other_categories_save_no_size_or_fit(client):
    """Scenario: Post each of the 8 other categories with a size and fit attached.

    Expected: Saved, but size and fit are dropped to empty.
    """
    # Size and fit are sent on purpose, to prove the server drops them.
    for category in appmod.ALLOWED_CATEGORIES:
        if category in ("Clothing", "Shoes"):
            continue
        res = post(client, category=category)
        assert res.status_code == 201
        assert saved(res.get_json()["id"]) == (category, "New", None, None)

def test_used_condition_is_saved(client):
    """Scenario: Post a Used listing.

    Expected: Condition saved as Used.
    """
    res = post(client, condition="Used")
    assert res.status_code == 201
    assert saved(res.get_json()["id"])[1] == "Used"

def test_bad_category_is_rejected(client):
    """Scenario: Post a category that is not on the list, or no category.

    Expected: Rejected with 400, "Please pick a valid category.".
    """
    res = post(client, category="Weapons")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Please pick a valid category."

def test_missing_category_is_rejected(client):
    """Scenario: Post a category that is not on the list, or no category.

    Expected: Rejected with 400, "Please pick a valid category.".
    """
    res = post(client, category=None)
    assert res.status_code == 400

def test_bad_condition_is_rejected(client):
    """Scenario: Post a condition that is not New or Used.

    Expected: Rejected with 400.
    """
    res = post(client, condition="Broken")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Please pick a valid condition."

def test_clothing_needs_a_fit(client):
    """Scenario: Post clothing with no fit.

    Expected: Rejected with 400, "Please pick a fit.".
    """
    res = post(client, fit=None)
    assert res.status_code == 400
    assert res.get_json()["error"] == "Please pick a fit."

def test_clothing_needs_a_real_size(client):
    """Scenario: Post clothing with a shoe size.

    Expected: Rejected with 400, "Please pick a valid size.".
    """
    res = post(client, size="US 8")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Please pick a valid size."

def test_shoe_size_has_to_be_in_range(client):
    """Scenario: Post shoes at US 15, US 16 and a clothing size.

    Expected: US 15 saved, the other two rejected.
    """
    assert post(client, category="Shoes", size="US 15").status_code == 201
    assert post(client, category="Shoes", size="US 16").status_code == 400
    assert post(client, category="Shoes", size="M").status_code == 400

def test_nothing_is_saved_when_the_fields_are_bad(client):
    """Scenario: Post with bad fields, then count the listings.

    Expected: Nothing was saved.
    """
    post(client, category="Weapons")
    assert query("SELECT COUNT(*) FROM listings")[0][0] == 0

def test_editing_changes_size_and_fit(client):
    """Scenario: Edit a listing to a new size and fit.

    Expected: New values saved.
    """
    listing_id = post(client).get_json()["id"]
    res = client.put("/api/listings/%s" % listing_id,
                     json={"user_id": seller_id(), "role": "user", "title": "Test item", "price": 20,
                           "category": "Clothing", "condition": "Used", "image": "x", "size": "XL", "fit": "Unisex"})
    assert res.status_code == 200
    assert saved(listing_id) == ("Clothing", "Used", "XL", "Unisex")

def test_editing_into_another_category_clears_size_and_fit(client):
    """Scenario: Edit a clothing listing into Books.

    Expected: Size and fit are cleared.
    """
    listing_id = post(client).get_json()["id"]
    client.put("/api/listings/%s" % listing_id,
               json={"user_id": seller_id(), "role": "user", "title": "Now a book", "price": 5,
                     "category": "Books", "condition": "Used", "image": "x", "size": "M", "fit": "Women's"})
    assert saved(listing_id) == ("Books", "Used", None, None)

def test_editing_with_a_bad_category_is_rejected(client):
    """Scenario: Edit a listing to a bad category.

    Expected: Rejected with 400.
    """
    listing_id = post(client).get_json()["id"]
    res = client.put("/api/listings/%s" % listing_id,
                     json={"user_id": seller_id(), "role": "user", "title": "x", "price": 5,
                           "category": "Nope", "condition": "New", "image": "x"})
    assert res.status_code == 400
