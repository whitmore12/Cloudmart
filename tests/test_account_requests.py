#Name: Makaila Williams
#test_account_requests.py: tests for account deletion requests
#needs a real postgres. set CLOUDMART_TEST_DSN to a throwaway database, like
#  CLOUDMART_TEST_DSN="host=127.0.0.1 port=5433 dbname=testdb user=postgres"
#the tables get wiped every test so never point it at the team database

import os
import sys

import bcrypt
import psycopg
import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import account_requests as ar  # noqa: E402

DSN = os.getenv("CLOUDMART_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set CLOUDMART_TEST_DSN to run these")

PASSWORD = "password123"
removedFiles = []
logged = []

#makeSchema
#purpose: fresh copy of the tables these routes touch, same shape as init_db in app.py
def makeSchema(conn):
    cur = conn.cursor()
    cur.execute("""
        DROP TABLE IF EXISTS account_deletion_requests, password_resets, transactions, wishlist, return_requests, listings, users CASCADE;
        CREATE TABLE users (
            id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE, username VARCHAR(50) UNIQUE,
            password_hash TEXT, role VARCHAR(20) DEFAULT 'user', profile_image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE listings (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), title VARCHAR(255),
            price NUMERIC, seller VARCHAR(100), buyer_email VARCHAR(255), status VARCHAR(20) DEFAULT 'active');
        CREATE TABLE wishlist (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            listing_id INTEGER REFERENCES listings(id), UNIQUE(user_id, listing_id));
        CREATE TABLE return_requests (
            id SERIAL PRIMARY KEY, listing_id INTEGER REFERENCES listings(id),
            seller_id INTEGER REFERENCES users(id), buyer_id INTEGER REFERENCES users(id),
            buyer_email VARCHAR(255) NOT NULL, reason TEXT NOT NULL, status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE password_resets (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE, expires_at TIMESTAMP, used BOOLEAN NOT NULL DEFAULT FALSE);
        CREATE TABLE transactions (
            id SERIAL PRIMARY KEY, from_user_id INTEGER REFERENCES users(id), to_user_id INTEGER REFERENCES users(id),
            amount NUMERIC, type VARCHAR(20), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()
    cur.close()

#addUser
#purpose: puts a user in the db and gives back the id
def addUser(name, role="user", image=None):
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    cur.execute("INSERT INTO users (email, username, password_hash, role, profile_image) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (name + "@my.hamptonu.edu", name, hashed, role, image))
    newId = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return newId

#query
#purpose: runs a select and gives back all rows
def query(sql, args=()):
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    conn.close()
    return rows

#run
#purpose: runs one write statement
def run(sql, args=()):
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    conn.close()

@pytest.fixture
def client():
    conn = psycopg.connect(DSN)
    makeSchema(conn)
    conn.close()
    removedFiles.clear()
    logged.clear()
    ar.failedTries.clear()
    app = Flask(__name__)
    app.config["TESTING"] = True
    ar.initAccountRequests(app, lambda: psycopg.connect(DSN), removedFiles.append,
                           lambda who, action, target: logged.append((who, action, target)))
    return app.test_client()

#backdate
#purpose: makes a request look older so we do not have to wait for the cooldown
def backdate(userId, amount):
    run("UPDATE account_deletion_requests SET reviewed_at = CURRENT_TIMESTAMP - %s::interval WHERE user_id = %s", (amount, userId))

#ask
#purpose: user sends a deletion request
def ask(client, userId, password=PASSWORD, reason="graduating"):
    return client.post("/api/account-requests", json={"user_id": userId, "password": password, "reason": reason})

#review
#purpose: admin reviews a request
def review(client, requestId, adminId, action, password=PASSWORD, note=""):
    return client.put("/api/admin/account-requests/%s/review" % requestId,
                      json={"admin_id": adminId, "action": action, "admin_password": password, "admin_note": note})

def test_request_needs_right_password(client):
    uid = addUser("mak")
    assert ask(client, uid, password="nope").status_code == 401
    assert ask(client, uid).status_code == 201

def test_only_one_pending_request(client):
    uid = addUser("mak")
    assert ask(client, uid).status_code == 201
    assert ask(client, uid).status_code == 409

def test_password_lockout(client):
    uid = addUser("mak")
    for _ in range(ar.MAX_TRIES):
        ask(client, uid, password="nope")
    assert ask(client, uid).status_code == 429

def test_reason_too_long(client):
    uid = addUser("mak")
    assert ask(client, uid, reason="x" * (ar.REASON_MAX + 1)).status_code == 400

def test_mine_shows_latest_and_cancel_works(client):
    uid = addUser("mak")
    assert client.get("/api/account-requests/mine?user_id=%s" % uid).get_json()["request"] is None
    reqId = ask(client, uid).get_json()["request_id"]
    assert client.get("/api/account-requests/mine?user_id=%s" % uid).get_json()["request"]["status"] == "pending"
    other = addUser("other")
    assert client.put("/api/account-requests/%s/cancel" % reqId, json={"user_id": other}).status_code == 404
    assert client.put("/api/account-requests/%s/cancel" % reqId, json={"user_id": uid}).status_code == 200
    assert client.get("/api/account-requests/mine?user_id=%s" % uid).get_json()["request"]["status"] == "cancelled"
    #right after a cancel they have to wait, then they can ask again
    assert ask(client, uid).status_code == 429
    backdate(uid, "2 hours")
    assert ask(client, uid).status_code == 201

def test_admin_list_blocks_regular_users(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    ask(client, uid)
    assert client.get("/api/admin/account-requests?admin_id=%s" % uid).status_code == 403
    rows = client.get("/api/admin/account-requests?admin_id=%s&status=pending" % adm).get_json()
    assert len(rows) == 1 and rows[0]["username"] == "mak"

def test_regular_user_cannot_review(client):
    uid = addUser("mak")
    other = addUser("other")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, other, "approve").status_code == 403

def test_deny_keeps_the_account(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "deny", note="talk to us first").status_code == 200
    assert query("SELECT username, role FROM users WHERE id=%s", (uid,))[0] == ("mak", "user")
    assert review(client, reqId, adm, "deny").status_code == 400

def test_approve_needs_admin_password(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve", password="wrong").status_code == 403
    assert query("SELECT username FROM users WHERE id=%s", (uid,))[0][0] == "mak"

def test_approve_wipes_the_account(client):
    uid = addUser("mak", image="/api/profile-images/profiles/abc.png")
    buyer = addUser("buyer")
    adm = addUser("boss", "admin")
    run("INSERT INTO listings (user_id, title, price, seller, status) VALUES (%s,'fridge',10,'mak','active')", (uid,))
    run("INSERT INTO listings (user_id, title, price, seller, status, buyer_email) VALUES (%s,'lamp',5,'mak','sold','buyer@my.hamptonu.edu')", (uid,))
    run("INSERT INTO listings (user_id, title, price, seller, status, buyer_email) VALUES (%s,'desk',5,'buyer','sold','mak@my.hamptonu.edu')", (buyer,))
    run("INSERT INTO wishlist (user_id, listing_id) VALUES (%s, 3)", (uid,))

    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 200

    assert query("SELECT username, email, role, profile_image FROM users WHERE id=%s", (uid,))[0] == (
        "deleted_%s" % uid, "deleted_%s@deleted.invalid" % uid, "deleted", None)
    listings = {r[0]: r[1:] for r in query("SELECT title, status, seller, buyer_email FROM listings")}
    assert listings["fridge"][0] == "deleted"
    assert listings["lamp"][0] == "sold"
    assert listings["lamp"][1] == "deleted_%s" % uid
    #the old email is gone from the desk they bought
    assert listings["desk"][2] == "deleted_%s@deleted.invalid" % uid
    assert query("SELECT COUNT(*) FROM wishlist WHERE user_id=%s", (uid,))[0][0] == 0
    assert removedFiles == ["/api/profile-images/profiles/abc.png"]
    assert query("SELECT status, admin_id FROM account_deletion_requests WHERE id=%s", (reqId,))[0] == ("approved", adm)

    #cant log in with the old password, cant ask again
    assert not ar.passwordMatches(PASSWORD, query("SELECT password_hash FROM users WHERE id=%s", (uid,))[0][0])
    assert ask(client, uid).status_code == 401

def test_pending_returns_block_deletion(client):
    uid = addUser("mak")
    buyer = addUser("buyer")
    run("INSERT INTO listings (user_id, title, price, seller, status, buyer_email) VALUES (%s,'lamp',5,'mak','sold','buyer@my.hamptonu.edu')", (uid,))
    run("INSERT INTO return_requests (listing_id, seller_id, buyer_id, buyer_email, reason) VALUES (1,%s,%s,'buyer@my.hamptonu.edu','broken')", (uid, buyer))
    #both sides are held, the seller and the buyer
    for who in (uid, buyer):
        res = ask(client, who)
        assert res.status_code == 409
        assert "return" in res.get_json()["error"].lower()
    assert query("SELECT COUNT(*) FROM account_deletion_requests")[0][0] == 0

def test_admin_cannot_approve_own_request(client):
    adm = addUser("boss", "admin")
    addUser("boss2", "admin")
    reqId = ask(client, adm).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 400

def test_admin_deleted_by_another_admin(client):
    adm = addUser("boss", "admin")
    other = addUser("boss2", "admin")
    reqId = ask(client, adm).get_json()["request_id"]
    assert review(client, reqId, other, "approve").status_code == 200
    assert query("SELECT role FROM users WHERE id=%s", (adm,))[0][0] == "deleted"
    #a deleted admin cant review anything anymore
    assert client.get("/api/admin/account-requests?admin_id=%s" % adm).status_code == 403

def test_blockers_stops_the_only_admin(client):
    adm = addUser("boss", "admin")
    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    assert any("only admin" in p for p in ar.blockers(cur, adm))
    addUser("boss2", "admin")
    assert ar.blockers(cur, adm) == []
    conn.close()


#bad input and sneaky input tests

def test_request_with_bad_input(client):
    uid = addUser("mak")
    assert client.post("/api/account-requests", data="not json", content_type="text/plain").status_code == 400
    assert client.post("/api/account-requests", json={}).status_code == 400
    assert client.post("/api/account-requests", json={"user_id": "abc", "password": PASSWORD}).status_code == 400
    assert client.post("/api/account-requests", json={"user_id": uid}).status_code == 400
    assert client.post("/api/account-requests", json={"user_id": uid, "password": ""}).status_code == 400

def test_request_for_user_that_does_not_exist(client):
    assert ask(client, 99999).status_code == 401

def test_deleted_user_cannot_ask_again(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    review(client, reqId, adm, "approve")
    assert ask(client, uid).status_code == 401
    assert ask(client, uid, password="anything").status_code == 401

def test_mine_and_cancel_with_bad_input(client):
    assert client.get("/api/account-requests/mine").status_code == 400
    assert client.get("/api/account-requests/mine?user_id=abc").status_code == 400
    assert client.put("/api/account-requests/1/cancel", json={}).status_code == 400
    assert client.put("/api/account-requests/1/cancel", json={"user_id": "abc"}).status_code == 400

def test_review_with_bad_action_or_missing_admin(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "delete").status_code == 400
    assert review(client, reqId, adm, "").status_code == 400
    res = client.put("/api/admin/account-requests/%s/review" % reqId, json={"action": "deny"})
    assert res.status_code == 400
    res = client.put("/api/admin/account-requests/%s/review" % reqId, json={"admin_id": "abc", "action": "deny"})
    assert res.status_code == 400
    #nothing changed
    assert query("SELECT status FROM account_deletion_requests WHERE id=%s", (reqId,))[0][0] == "pending"

def test_review_note_too_long(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "deny", note="x" * (ar.NOTE_MAX + 1)).status_code == 400

def test_review_request_that_does_not_exist(client):
    adm = addUser("boss", "admin")
    assert review(client, 99999, adm, "deny").status_code == 404
    assert review(client, 99999, adm, "approve").status_code == 404

def test_review_by_admin_id_that_does_not_exist(client):
    uid = addUser("mak")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, 99999, "deny").status_code == 403

def test_admin_list_bad_input(client):
    adm = addUser("boss", "admin")
    assert client.get("/api/admin/account-requests").status_code == 400
    assert client.get("/api/admin/account-requests?admin_id=abc").status_code == 400
    assert client.get("/api/admin/account-requests?admin_id=%s&status=bogus" % adm).status_code == 400
    assert client.get("/api/admin/account-requests?admin_id=99999").status_code == 403

def test_admin_password_lockout(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    for _ in range(ar.MAX_TRIES):
        assert review(client, reqId, adm, "approve", password="nope").status_code == 403
    #even the right password is refused while locked
    assert review(client, reqId, adm, "approve").status_code == 429
    assert query("SELECT username FROM users WHERE id=%s", (uid,))[0][0] == "mak"

def test_picture_delete_failing_does_not_stop_deletion(client):
    uid = addUser("mak", image="/api/profile-images/profiles/abc.png")
    adm = addUser("boss", "admin")

    def boom(url):
        raise RuntimeError("s3 is down")
    ar.fileRemover = boom
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 200
    assert query("SELECT role FROM users WHERE id=%s", (uid,))[0][0] == "deleted"

def test_sql_injection_is_just_text(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    evil = "'); DROP TABLE users; --"
    assert ask(client, uid, reason=evil).status_code == 201
    #users table still there and the evil text was saved as plain text
    assert query("SELECT COUNT(*) FROM users")[0][0] == 2
    assert query("SELECT reason FROM account_deletion_requests")[0][0] == evil
    #injection through the number and filter fields gets rejected
    assert client.get("/api/account-requests/mine?user_id=1;DROP TABLE users").status_code == 400
    assert client.get("/api/admin/account-requests?admin_id=%s&status=pending' OR '1'='1" % adm).status_code == 400
    assert query("SELECT COUNT(*) FROM users")[0][0] == 2

def test_reason_is_trimmed_and_blank_is_allowed(client):
    uid = addUser("mak")
    assert ask(client, uid, reason="   ").status_code == 201
    assert query("SELECT reason FROM account_deletion_requests")[0][0] is None


#holds and cooldowns, deleting is for leaving and not for dodging

def test_recent_finished_return_still_holds(client):
    uid = addUser("mak")
    buyer = addUser("buyer")
    run("INSERT INTO listings (user_id, title, price, seller, status) VALUES (%s,'lamp',5,'mak','active')", (uid,))
    run("INSERT INTO return_requests (listing_id, seller_id, buyer_id, buyer_email, reason, status) VALUES (1,%s,%s,'b@x','broken','denied')", (uid, buyer))
    assert ask(client, uid).status_code == 409
    #old enough, it no longer holds
    run("UPDATE return_requests SET created_at = CURRENT_TIMESTAMP - interval '31 days'")
    assert ask(client, uid).status_code == 201

def test_old_pending_return_still_holds(client):
    uid = addUser("mak")
    buyer = addUser("buyer")
    run("INSERT INTO listings (user_id, title, price, seller, status) VALUES (%s,'lamp',5,'mak','sold')", (uid,))
    run("INSERT INTO return_requests (listing_id, seller_id, buyer_id, buyer_email, reason, created_at) VALUES (1,%s,%s,'b@x','broken', CURRENT_TIMESTAMP - interval '90 days')", (uid, buyer))
    assert ask(client, uid).status_code == 409

def test_recent_sale_or_purchase_holds(client):
    seller = addUser("seller")
    buyer = addUser("buyer")
    run("INSERT INTO transactions (from_user_id, to_user_id, amount, type) VALUES (%s,%s,5,'sale')", (buyer, seller))
    for who in (seller, buyer):
        res = ask(client, who)
        assert res.status_code == 409
        assert "bought or sold" in res.get_json()["error"]
    run("UPDATE transactions SET created_at = CURRENT_TIMESTAMP - interval '31 days'")
    assert ask(client, seller).status_code == 201
    assert ask(client, buyer).status_code == 201

def test_someone_with_no_activity_is_not_held(client):
    uid = addUser("mak")
    addUser("other")
    assert ask(client, uid).status_code == 201

def test_hold_is_checked_again_at_approval(client):
    uid = addUser("mak")
    other = addUser("other")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    #they sold something after asking, so the admin cant approve yet
    run("INSERT INTO transactions (from_user_id, to_user_id, amount, type) VALUES (%s,%s,5,'sale')", (other, uid))
    res = review(client, reqId, adm, "approve")
    assert res.status_code == 409
    assert "bought or sold" in res.get_json()["error"]
    assert query("SELECT username FROM users WHERE id=%s", (uid,))[0][0] == "mak"
    assert query("SELECT status FROM account_deletion_requests WHERE id=%s", (reqId,))[0][0] == "pending"

def test_only_admin_cannot_even_ask(client):
    adm = addUser("boss", "admin")
    res = ask(client, adm)
    assert res.status_code == 409
    assert "only admin" in res.get_json()["error"]

def test_cooldown_after_cancel(client):
    uid = addUser("mak")
    reqId = ask(client, uid).get_json()["request_id"]
    client.put("/api/account-requests/%s/cancel" % reqId, json={"user_id": uid})
    res = ask(client, uid)
    assert res.status_code == 429
    assert "minutes" in res.get_json()["error"]
    backdate(uid, "59 minutes")
    assert ask(client, uid).status_code == 429
    backdate(uid, "61 minutes")
    assert ask(client, uid).status_code == 201

def test_cooldown_after_deny_is_longer(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    review(client, reqId, adm, "deny")
    res = ask(client, uid)
    assert res.status_code == 429
    assert "hours" in res.get_json()["error"]
    backdate(uid, "2 hours")
    assert ask(client, uid).status_code == 429
    backdate(uid, "25 hours")
    assert ask(client, uid).status_code == 201

def test_wrong_password_still_gets_401_during_cooldown(client):
    uid = addUser("mak")
    reqId = ask(client, uid).get_json()["request_id"]
    client.put("/api/account-requests/%s/cancel" % reqId, json={"user_id": uid})
    #the password is checked first so nobody learns anything without it
    assert ask(client, uid, password="nope").status_code == 401

def test_waitText():
    assert ar.waitText(30) == "1 minutes"
    assert ar.waitText(600) == "10 minutes"
    assert ar.waitText(3 * 3600) == "3 hours"


#things the team added after the first version, password resets and the action log

def test_reset_link_from_before_the_delete_stops_working(client):
    uid = addUser("mak")
    other = addUser("other")
    adm = addUser("boss", "admin")
    run("INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (%s,'abc', CURRENT_TIMESTAMP + interval '30 minutes')", (uid,))
    run("INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (%s,'def', CURRENT_TIMESTAMP + interval '30 minutes')", (other,))
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 200
    used = dict(query("SELECT token_hash, used FROM password_resets"))
    assert used["abc"] is True
    #someone elses link is left alone
    assert used["def"] is False

def test_delete_still_works_if_there_is_no_password_resets_table(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    run("DROP TABLE password_resets")
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 200
    assert query("SELECT role FROM users WHERE id=%s", (uid,))[0][0] == "deleted"

def test_requests_and_decisions_go_in_the_action_log(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    reqId = ask(client, uid).get_json()["request_id"]
    review(client, reqId, adm, "approve")
    assert logged == [
        ("User %s" % uid, "REQUEST_ACCOUNT_DELETION", "User #%s" % uid),
        ("Admin (ID: %s)" % adm, "APPROVE_ACCOUNT_DELETION", "User #%s" % uid),
    ]

def test_deny_is_logged_too_and_blocked_attempts_are_not(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")
    ask(client, uid, password="nope")
    assert logged == []
    reqId = ask(client, uid).get_json()["request_id"]
    review(client, reqId, adm, "deny")
    assert logged[-1] == ("Admin (ID: %s)" % adm, "DENY_ACCOUNT_DELETION", "User #%s" % uid)

def test_a_broken_logger_does_not_stop_anything(client):
    uid = addUser("mak")
    adm = addUser("boss", "admin")

    def boom(who, action, target):
        raise RuntimeError("log table is gone")
    ar.actionLogger = boom
    reqId = ask(client, uid).get_json()["request_id"]
    assert review(client, reqId, adm, "approve").status_code == 200
    assert query("SELECT role FROM users WHERE id=%s", (uid,))[0][0] == "deleted"

def test_no_logger_given_is_fine(client):
    uid = addUser("mak")
    ar.actionLogger = None
    assert ask(client, uid).status_code == 201
