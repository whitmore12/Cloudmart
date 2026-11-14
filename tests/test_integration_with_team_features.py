"""Integration tests: the purchase flow against the rest of the app.

Scope:    one buyer (alice) wins an item and another (bob) loses it. The tests
          then walk the other features that touch the same listing: wallet,
          wishlist, pending and bought lists, returns, the admin PIN bypass, and
          edit / delete. The point is that bob is never left believing the item
          is still available, anywhere.
Run:      CLOUDMART_TEST_DSN="host=127.0.0.1 port=5433 dbname=cloudmart_test user=postgres" pytest tests/test_integration_with_team_features.py
Safety:   the database is wiped before every test, so its name must contain "test".

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

PRICE = 10
START = 1000
EMAIL = "%s@my.hamptonu.edu"

def query(sql, args=()):
    """Run a SELECT on the test database and return every row."""
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    conn.close()
    return rows

def run(sql, args=()):
    """Run one write statement on the test database and commit it."""
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    conn.close()

@pytest.fixture
def world(monkeypatch):
    """Seller, alice, bob and an admin, plus one clothing listing for sale."""
    # Cast: a seller, alice (wins), bob (loses) and an admin, plus one clothing listing for sale.
    monkeypatch.setattr(appmod, "get_db_connection", lambda: psycopg.connect(DSN))
    reset_database(DSN)
    appmod.init_db()
    appmod.app.config["TESTING"] = True
    run("TRUNCATE transactions, return_requests, wishlist, listings, users RESTART IDENTITY CASCADE")
    for name in ("seller", "alice", "bob", "admin"):
        role = "admin" if name == "admin" else "user"
        run("INSERT INTO users (email, username, password_hash, pirate_dollars, role) VALUES (%s, %s, 'x', %s, %s)",
            (EMAIL % name, name, START, role))
    ids = {row[1]: row[0] for row in query("SELECT id, username FROM users")}
    run("INSERT INTO listings (user_id, title, price, category, condition, image, seller, status, size, fit) "
        "VALUES (%s, 'Hoodie', %s, 'Clothing', 'New', 'img', 'seller', 'active', 'M', 'Women''s')", (ids["seller"], PRICE))
    ids["listing"] = query("SELECT MAX(id) FROM listings")[0][0]
    ids["client"] = appmod.app.test_client()
    return ids

def buy(w, name):
    """POST an initiate-purchase request as the named buyer."""
    return w["client"].post("/api/listings/%s/initiate-purchase" % w["listing"], json={"user_id": w[name], "role": "user"})

def pin_of(w):
    """Return the PIN stored for the scenario's listing."""
    return query("SELECT verification_pin FROM listings WHERE id = %s", (w["listing"],))[0][0]

def confirm(w):
    """POST a confirm-purchase request as the seller, using the stored PIN."""
    return w["client"].post("/api/listings/%s/confirm-purchase" % w["listing"],
                            json={"user_id": w["seller"], "role": "user", "pin": pin_of(w)})

def wish(w, name):
    """Add the scenario's listing to a user's wishlist."""
    return w["client"].post("/api/wishlist", json={"user_id": w[name], "listing_id": w["listing"]})

def balance(w, name):
    """Read a user's balance through the wallet endpoint."""
    return w["client"].get("/api/wallet/balance?user_id=%s" % w[name]).get_json()["balance"]

def titles(res):
    """Return the titles in a JSON list of listings."""
    return [i["title"] for i in res.get_json()]

def untouched(w, name):
    """Assert a user kept their full balance and has no wallet history."""
    assert balance(w, name) == START
    history = w["client"].get("/api/wallet/history?user_id=%s" % w[name]).get_json()
    assert history == []

# --- Marketplace ---

def test_marketplace_stops_showing_the_item_once_someone_wins(world):
    """Scenario: Alice wins the item, then the marketplace is loaded.

    Expected: The item is gone from the marketplace.
    """
    assert "Hoodie" in titles(world["client"].get("/api/listings"))
    assert buy(world, "alice").status_code == 200
    assert "Hoodie" not in titles(world["client"].get("/api/listings"))

def test_item_keeps_its_size_and_fit_through_the_whole_sale(world):
    """Scenario: A clothing item goes through the full sale.

    Expected: It keeps its size and fit after it is sold.
    """
    buy(world, "alice")
    confirm(world)
    listing = world["client"].get("/api/listings/%s" % world["listing"]).get_json()
    assert listing["status"] == "sold"
    assert listing["size"] == "M" and listing["fit"] == "Women's"

# --- Wishlist ---

def test_wishlist_of_the_loser_no_longer_shows_the_item(world):
    """Scenario: Both put the item on their wishlist, then Alice wins.

    Expected: The item is gone from both wishlists.
    """
    wish(world, "alice")
    wish(world, "bob")
    assert titles(world["client"].get("/api/wishlist?user_id=%s" % world["bob"])) == ["Hoodie"]
    buy(world, "alice")
    assert titles(world["client"].get("/api/wishlist?user_id=%s" % world["bob"])) == []
    assert titles(world["client"].get("/api/wishlist?user_id=%s" % world["alice"])) == []

def test_wishlist_item_comes_back_if_the_purchase_expires(world):
    """Scenario: Bob has it wishlisted, Alice wins, then her PIN expires.

    Expected: The item comes back on Bob's wishlist.
    """
    wish(world, "bob")
    buy(world, "alice")
    run("UPDATE listings SET pin_expires_at = NOW() - INTERVAL '1 hour' WHERE id = %s", (world["listing"],))
    confirm(world)
    assert titles(world["client"].get("/api/wishlist?user_id=%s" % world["bob"])) == ["Hoodie"]

# --- Wallet ---

def test_wallet_shows_the_winner_paid_and_the_loser_did_not(world):
    """Scenario: Alice wins and Bob loses, then check the wallet.

    Expected: Alice paid, and Bob has all his money and no history.
    """
    buy(world, "alice")
    assert buy(world, "bob").status_code == 409
    assert balance(world, "alice") == START - PRICE
    untouched(world, "bob")

def test_wallet_pays_the_seller_once_at_confirm(world):
    """Scenario: Seller confirms the sale.

    Expected: The seller is paid once through the wallet.
    """
    buy(world, "alice")
    assert balance(world, "seller") == START
    assert confirm(world).status_code == 200
    assert balance(world, "seller") == START + PRICE
    assert balance(world, "alice") == START - PRICE

def test_wallet_history_records_the_winners_purchase_only(world):
    """Scenario: Both try to buy, then the seller confirms.

    Expected: Alice's history has her purchase once and nothing from Bob.
    """
    buy(world, "alice")
    buy(world, "bob")
    confirm(world)
    types = [t["type"] for t in world["client"].get("/api/wallet/history?user_id=%s" % world["alice"]).get_json()]
    assert "purchase_pending" in types
    assert types.count("purchase") == 1

def test_wallet_gets_the_money_back_when_the_pin_expires(world):
    """Scenario: Alice wins and her PIN expires.

    Expected: Alice has her money back and the seller was not paid.
    """
    buy(world, "alice")
    run("UPDATE listings SET pin_expires_at = NOW() - INTERVAL '1 hour' WHERE id = %s", (world["listing"],))
    confirm(world)
    assert balance(world, "alice") == START
    assert balance(world, "seller") == START

# --- Pending and bought lists ---

def test_winner_sees_the_item_in_pending_with_the_pin_and_loser_sees_nothing(world):
    """Scenario: Both try to buy.

    Expected: Alice sees it in her pending list with the PIN, Bob's pending list is empty.
    """
    buy(world, "alice")
    buy(world, "bob")
    mine = world["client"].get("/api/listings/pending/%s" % (EMAIL % "alice")).get_json()
    assert [i["title"] for i in mine] == ["Hoodie"]
    assert mine[0]["verification_pin"] == pin_of(world)
    assert world["client"].get("/api/listings/pending/%s" % (EMAIL % "bob")).get_json() == []

def test_seller_sees_the_pending_sale(world):
    """Scenario: Alice wins.

    Expected: The seller sees the pending sale.
    """
    buy(world, "alice")
    res = world["client"].get("/api/listings/pending?user_id=%s&role=user" % world["seller"])
    assert titles(res) == ["Hoodie"]

def test_after_confirm_the_item_moves_from_pending_to_bought(world):
    """Scenario: The seller confirms.

    Expected: The item leaves pending and shows in Alice's bought items, not Bob's.
    """
    buy(world, "alice")
    confirm(world)
    assert world["client"].get("/api/listings/pending/%s" % (EMAIL % "alice")).get_json() == []
    bought = world["client"].get("/api/listings/bought/%s" % (EMAIL % "alice")).get_json()
    assert [i["title"] for i in bought] == ["Hoodie"]
    assert world["client"].get("/api/listings/bought/%s" % (EMAIL % "bob")).get_json() == []

# --- Returns ---

def test_winner_can_ask_for_a_return_after_the_sale(world):
    """Scenario: Alice asks for a return after the sale.

    Expected: The return request is accepted.
    """
    buy(world, "alice")
    confirm(world)
    res = world["client"].post("/api/returns/request", json={
        "listing_id": world["listing"], "buyer_id": world["alice"], "buyer_email": EMAIL % "alice", "reason": "too small"})
    assert res.status_code == 201

def test_loser_cannot_ask_for_a_return(world):
    """Scenario: Bob asks for a return on an item he lost.

    Expected: Refused with 403.
    """
    buy(world, "alice")
    confirm(world)
    res = world["client"].post("/api/returns/request", json={
        "listing_id": world["listing"], "buyer_id": world["bob"], "buyer_email": EMAIL % "bob", "reason": "want it"})
    assert res.status_code == 403

# --- Admin tools ---

def test_admin_bypass_still_completes_the_sale_for_the_winner(world):
    """Scenario: An admin bypasses the PIN.

    Expected: The sale completes and the seller is paid.
    """
    buy(world, "alice")
    res = world["client"].post("/api/listings/%s/admin-bypass-pin" % world["listing"],
                               json={"user_id": world["admin"], "role": "admin"})
    assert res.status_code == 200
    assert world["client"].get("/api/listings/%s" % world["listing"]).get_json()["status"] == "sold"
    assert balance(world, "seller") == START + PRICE

def test_admin_bypass_is_still_admin_only(world):
    """Scenario: A regular user tries the admin bypass.

    Expected: Refused with 403.
    """
    buy(world, "alice")
    res = world["client"].post("/api/listings/%s/admin-bypass-pin" % world["listing"],
                               json={"user_id": world["bob"], "role": "user"})
    assert res.status_code == 403

# --- Edit, delete and self-purchase ---

def test_deleted_item_cannot_be_bought_and_the_buyer_is_not_charged(world):
    """Scenario: The seller deletes the item, then Bob tries to buy.

    Expected: He gets "no longer available" and is not charged.
    """
    res = world["client"].delete("/api/listings/%s" % world["listing"], json={"user_id": world["seller"], "role": "user"})
    assert res.status_code == 200
    assert buy(world, "bob").status_code == 409
    untouched(world, "bob")

def test_buyer_pays_the_price_at_checkout_if_the_seller_changed_it(world):
    """Scenario: The seller changes the price after it was in a cart.

    Expected: The buyer pays the new price at checkout.
    """
    world["client"].put("/api/listings/%s" % world["listing"], json={
        "user_id": world["seller"], "role": "user", "title": "Hoodie", "price": 25, "category": "Clothing",
        "condition": "New", "image": "img", "size": "M", "fit": "Women's"})
    assert buy(world, "alice").status_code == 200
    assert balance(world, "alice") == START - 25

def test_seller_buying_their_own_item_is_a_normal_error_not_a_409(world):
    """Scenario: The seller tries to buy their own item.

    Expected: A normal 400 error, not a 409, and the item stays active.
    """
    res = buy(world, "seller")
    assert res.status_code == 400
    assert "own listing" in res.get_json()["error"]
    assert world["client"].get("/api/listings/%s" % world["listing"]).get_json()["status"] == "active"

# --- Every place the loser could look ---

def test_after_losing_the_item_is_gone_from_every_place_bob_could_find_it(world):
    """Scenario: Alice wins, then check every place Bob could find the item.

    Expected: Gone from the marketplace, his wishlist, pending, bought and the item itself is not active, and he is not charged.
    """
    wish(world, "bob")
    buy(world, "alice")
    assert buy(world, "bob").status_code == 409
    assert "Hoodie" not in titles(world["client"].get("/api/listings"))
    assert titles(world["client"].get("/api/wishlist?user_id=%s" % world["bob"])) == []
    assert world["client"].get("/api/listings/pending/%s" % (EMAIL % "bob")).get_json() == []
    assert world["client"].get("/api/listings/bought/%s" % (EMAIL % "bob")).get_json() == []
    assert world["client"].get("/api/listings/%s" % world["listing"]).get_json()["status"] != "active"
    untouched(world, "bob")
