"""Concurrency tests for buying a one-of-a-kind item.

Scope:    several buyers pressing checkout at the same instant, and a seller
          double-clicking Confirm. Requests are released together from separate
          threads with a barrier, then the database is inspected afterwards.
Rounds:   each scenario repeats ROUNDS times, because a race condition does not
          show up on every attempt. A single green run proves very little.
Run:      CLOUDMART_TEST_DSN="host=127.0.0.1 port=5433 dbname=cloudmart_test user=postgres" pytest tests/test_race_condition.py
Safety:   the database is wiped before every test, so its name must contain "test".

Author: Claude (Anthropic)
"""

import os
import sys
import threading
from datetime import datetime, timedelta

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

ROUNDS = 20
PRICE = 10
START = 1000

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

@pytest.fixture(autouse=True)
def database(monkeypatch):
    """Point the app at the throwaway database and rebuild its tables."""
    monkeypatch.setattr(appmod, "get_db_connection", lambda: psycopg.connect(DSN))
    reset_database(DSN)
    appmod.init_db()
    appmod.app.config["TESTING"] = True

def fresh():
    """Reset the database and create a seller plus two buyers holding START each. Returns their ids by username."""
    run("TRUNCATE transactions, listings, users RESTART IDENTITY CASCADE")
    for name in ("seller", "alice", "bob"):
        run("INSERT INTO users (email, username, password_hash, pirate_dollars) VALUES (%s, %s, 'x', %s)",
            (name + "@my.hamptonu.edu", name, START))
    return {row[1]: row[0] for row in query("SELECT id, username FROM users")}

def new_listing(seller_id):
    """Insert one active listing owned by the seller and return its id."""
    run("INSERT INTO listings (user_id, title, price, category, condition, image, seller, status) "
        "VALUES (%s, 'Hoodie', %s, 'Clothing', 'New', 'img', 'seller', 'active')", (seller_id, PRICE))
    return query("SELECT MAX(id) FROM listings")[0][0]

def balance(name):
    """Return a user's current balance."""
    return float(query("SELECT pirate_dollars FROM users WHERE username = %s", (name,))[0][0])

def listing_row(listing_id):
    """Return (status, buyer_email, verification_pin) for a listing."""
    return query("SELECT status, buyer_email, verification_pin FROM listings WHERE id = %s", (listing_id,))[0]

def count_transactions(kind):
    """Count the transactions of one type."""
    return query("SELECT COUNT(*) FROM transactions WHERE type = %s", (kind,))[0][0]

def buy(listing_id, user_id):
    """Return a callable that POSTs an initiate-purchase request for this buyer."""
    return lambda: appmod.app.test_client().post("/api/listings/%s/initiate-purchase" % listing_id,
                                                 json={"user_id": user_id, "role": "user"})

def confirm(listing_id, seller_id, pin):
    """Return a callable that POSTs a confirm-purchase request with this PIN."""
    return lambda: appmod.app.test_client().post("/api/listings/%s/confirm-purchase" % listing_id,
                                                 json={"user_id": seller_id, "role": "user", "pin": pin})

def fire_together(requests):
    """Release every callable at the same instant from its own thread and return the results in order."""
    gate = threading.Barrier(len(requests))
    results = [None] * len(requests)

    def go(i, send):
        gate.wait()
        results[i] = send()

    threads = [threading.Thread(target=go, args=(i, send)) for i, send in enumerate(requests)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results

def get_pin(listing_id):
    """Return the PIN stored for a listing."""
    return query("SELECT verification_pin FROM listings WHERE id = %s", (listing_id,))[0][0]

def test_two_buyers_only_one_wins():
    """Scenario: Two buyers press checkout on the same item at once.

    Expected: One gets 200, the other 409, item is pending.
    """
    for _ in range(ROUNDS):
        ids = fresh()
        listing_id = new_listing(ids["seller"])
        first, second = fire_together([buy(listing_id, ids["alice"]), buy(listing_id, ids["bob"])])
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        assert listing_row(listing_id)[0] == "pending"

def test_loser_is_told_it_is_gone_and_not_charged():
    """Scenario: Two buyers press checkout on the same item at once, then the balances are compared.

    Expected: The loser is not charged, exactly one person paid.
    """
    for _ in range(ROUNDS):
        ids = fresh()
        listing_id = new_listing(ids["seller"])
        results = fire_together([buy(listing_id, ids["alice"]), buy(listing_id, ids["bob"])])
        loser = [r for r in results if r.status_code == 409][0]
        assert "no longer available" in loser.get_json()["error"].lower() or "not available" in loser.get_json()["error"].lower()
        # Exactly one buyer paid; the other still holds the full balance.
        assert sorted([balance("alice"), balance("bob")]) == [START - PRICE, START]

def test_winner_gets_a_pin_and_the_item_is_theirs():
    """Scenario: Two buyers press checkout on the same item at once, then the winner is inspected.

    Expected: The winner got a PIN and is the buyer on the listing.
    """
    for _ in range(ROUNDS):
        ids = fresh()
        listing_id = new_listing(ids["seller"])
        results = fire_together([buy(listing_id, ids["alice"]), buy(listing_id, ids["bob"])])
        winner = [r for r in results if r.status_code == 200][0]
        pin = winner.get_json()["verification_pin"]
        assert pin == get_pin(listing_id)
        status, buyer_email, _ = listing_row(listing_id)
        assert status == "pending"
        assert buyer_email in ("alice@my.hamptonu.edu", "bob@my.hamptonu.edu")

def test_five_buyers_at_once_only_one_wins():
    """Scenario: Five buyers at once.

    Expected: One wins and four get 409, only one payment was made.
    """
    for _ in range(5):
        ids = fresh()
        for extra in ("cara", "dee", "eli"):
            run("INSERT INTO users (email, username, password_hash, pirate_dollars) VALUES (%s, %s, 'x', %s)",
                (extra + "@my.hamptonu.edu", extra, START))
        ids = {row[1]: row[0] for row in query("SELECT id, username FROM users")}
        listing_id = new_listing(ids["seller"])
        buyers = [ids[n] for n in ("alice", "bob", "cara", "dee", "eli")]
        results = fire_together([buy(listing_id, b) for b in buyers])
        codes = sorted(r.status_code for r in results)
        assert codes == [200, 409, 409, 409, 409]
        assert count_transactions("purchase_pending") == 1

def test_buying_a_pending_item_later_is_also_a_409():
    """Scenario: Buy an item that is already pending.

    Expected: 409 and no charge.
    """
    ids = fresh()
    listing_id = new_listing(ids["seller"])
    assert buy(listing_id, ids["alice"])().status_code == 200
    late = buy(listing_id, ids["bob"])()
    assert late.status_code == 409
    assert balance("bob") == START

def test_real_errors_are_not_409s():
    """Scenario: A buyer without enough money.

    Expected: 400 insufficient funds, not a 409, item stays active.
    """
    # 409 means "someone else got it first". A buyer who cannot pay must get the ordinary 400.
    ids = fresh()
    listing_id = new_listing(ids["seller"])
    run("UPDATE users SET pirate_dollars = 1 WHERE username = 'alice'")
    res = buy(listing_id, ids["alice"])()
    assert res.status_code == 400
    assert res.get_json()["error"] == "Insufficient funds"
    assert listing_row(listing_id)[0] == "active"

def test_double_click_on_confirm_pays_the_seller_once():
    """Scenario: Seller double clicks Confirm.

    Expected: Seller is paid once and the second click is refused.
    """
    for _ in range(ROUNDS):
        ids = fresh()
        listing_id = new_listing(ids["seller"])
        buy(listing_id, ids["alice"])()
        pin = get_pin(listing_id)
        results = fire_together([confirm(listing_id, ids["seller"], pin)] * 2)
        assert sorted(r.status_code for r in results) == [200, 400]
        assert balance("seller") == START + PRICE
        assert balance("alice") == START - PRICE
        assert listing_row(listing_id)[0] == "sold"
        assert count_transactions("sale") == 1

def test_double_click_on_an_expired_pin_refunds_once():
    """Scenario: Seller double clicks Confirm on an expired PIN.

    Expected: Buyer is refunded once, not twice.
    """
    for _ in range(ROUNDS):
        ids = fresh()
        listing_id = new_listing(ids["seller"])
        buy(listing_id, ids["alice"])()
        pin = get_pin(listing_id)
        run("UPDATE listings SET pin_expires_at = %s WHERE id = %s", (datetime.utcnow() - timedelta(hours=1), listing_id))
        fire_together([confirm(listing_id, ids["seller"], pin)] * 2)
        # The refund must land once, not twice.
        assert balance("alice") == START
        assert count_transactions("refund") == 1
        assert listing_row(listing_id)[0] == "active"

def test_after_an_expired_pin_the_next_buyer_can_buy():
    """Scenario: PIN expires, then a new buyer buys.

    Expected: The item is back for sale and the new buyer can buy it.
    """
    ids = fresh()
    listing_id = new_listing(ids["seller"])
    buy(listing_id, ids["alice"])()
    pin = get_pin(listing_id)
    run("UPDATE listings SET pin_expires_at = %s WHERE id = %s", (datetime.utcnow() - timedelta(hours=1), listing_id))
    confirm(listing_id, ids["seller"], pin)()
    assert buy(listing_id, ids["bob"])().status_code == 200
    assert balance("bob") == START - PRICE

def test_cart_check_sees_a_sold_item_as_gone():
    """Scenario: The cart asks the server about an item before and after a sale.

    Expected: Active before, not active after, and an unknown item is a 404.
    """
    # The cart page asks the server about every item on load; this is what it gets back.
    ids = fresh()
    listing_id = new_listing(ids["seller"])
    client = appmod.app.test_client()
    assert client.get("/api/listings/%s" % listing_id).get_json()["status"] == "active"
    buy(listing_id, ids["alice"])()
    assert client.get("/api/listings/%s" % listing_id).get_json()["status"] != "active"
    assert client.get("/api/listings/999999").status_code == 404
