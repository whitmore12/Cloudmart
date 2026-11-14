'''
Written by: Erick Constant
Purpose: To test the accuracy of the wallet


Re-authored with Claude Code
'''
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

import bcrypt
import pytest

# Make Wallet.py (in backend/) and application.py (in the project root) importable.
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)
import application  # noqa: E402
import Wallet  # noqa: E402
from Wallet import (  # noqa: E402
    get_balance,
    check_for_sufficient_funds,
    update_money,
    transfer_money,
    get_transaction_history,
)


# ---------- helpers (so no test ever touches the real database) ----------

def fake_db(monkeypatch, fetchone=None, fetchall=None, rowcount=1):
    '''
    Purpose: Replaces the database with a fake that returns the given rows.
    Returns: (connection, cursor) fakes, so tests can check what was called.
    '''
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall or []
    cur.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cur
    monkeypatch.setattr(Wallet, "get_db_connection", lambda: conn)
    return conn, cur


def fake_wallet(monkeypatch, balances):
    '''
    Purpose: Replaces the database with a simple dict like {user_id: balance}.
    Returns: The same dict, which changes as money moves.
    '''
    monkeypatch.setattr(Wallet, "get_balance", lambda uid: balances.get(uid, 0.0))

    def set_balance(uid, new_balance):
        balances[uid] = new_balance
        return True
    monkeypatch.setattr(Wallet, "update_money", set_balance)
    return balances


# ---------- get_balance ----------

def test_get_balance_existing_user(monkeypatch):
    '''
    Purpose: Tests that get_balance returns the user's balance as a float.
    Expected Result: Pass
    '''
    fake_db(monkeypatch, fetchone=(Decimal("20.50"),))
    assert get_balance(2) == 20.5


def test_get_balance_missing_user(monkeypatch):
    '''
    Purpose: Tests that get_balance returns 0.0 when the user does not exist.
    Expected Result: Pass
    '''
    fake_db(monkeypatch, fetchone=None)
    assert get_balance(999) == 0.0


# ---------- check_for_sufficient_funds ----------

def test_check_for_sufficient_funds(monkeypatch):
    '''
    Purpose: Tests that check_for_sufficient_funds is True when the balance
             covers the amount and False when it does not.
    Expected Result: Pass
    '''
    fake_wallet(monkeypatch, {1: 100.0})
    assert check_for_sufficient_funds(1, 50) is True
    assert check_for_sufficient_funds(1, 150) is False


def test_check_for_sufficient_funds_exact_balance(monkeypatch):
    '''
    Purpose: Tests that spending exactly the whole balance is allowed.
    Expected Result: Pass
    '''
    fake_wallet(monkeypatch, {1: 100.0})
    assert check_for_sufficient_funds(1, 100) is True


# ---------- update_money ----------

def test_update_money_saves_new_balance(monkeypatch):
    '''
    Purpose: Tests that update_money saves the new balance and commits it.
    Expected Result: Pass
    '''
    conn, cur = fake_db(monkeypatch, rowcount=1)
    assert update_money(1, 75.0) is True
    conn.commit.assert_called_once()


def test_update_money_unknown_user(monkeypatch):
    '''
    Purpose: Tests that update_money returns False when the user does not exist.
    Expected Result: Pass
    '''
    fake_db(monkeypatch, rowcount=0)
    assert update_money(999, 10) is False


# ---------- transfer_money ----------

def test_transfer_money_success(monkeypatch):
    '''
    Purpose: Tests that transfer_money moves money from the buyer to the seller.
    Expected Result: Pass (returns 0, buyer 100 -> 50, seller 20 -> 70)
    '''
    balances = fake_wallet(monkeypatch, {1: 100.0, 2: 20.0})
    assert transfer_money(1, 2, 50) == 0
    assert balances == {1: 50.0, 2: 70.0}


def test_transfer_money_insufficient_funds(monkeypatch):
    '''
    Purpose: Tests that transfer_money refuses to send more money than the
             buyer has, and changes nobody's balance.
    Expected Result: Pass (returns 1, balances unchanged)
    '''
    balances = fake_wallet(monkeypatch, {1: 100.0, 2: 20.0})
    assert transfer_money(1, 2, 150) == 1
    assert balances == {1: 100.0, 2: 20.0}


def test_transfer_money_to_unknown_seller(monkeypatch):
    '''
    Purpose: Tests that money cannot be sent to a user who does not exist.
    Expected Result: Fail (known bug: transfer_money never checks the seller,
                     so the buyer is charged and the money disappears)
    '''
    balances = fake_wallet(monkeypatch, {1: 100.0})
    assert transfer_money(1, 10, 50) == 1
    assert balances[1] == 100.0


# ---------- transfer from the wallet page (password confirmation) ----------

PASSWORD = "correct-horse-battery"


@pytest.fixture
def client(monkeypatch):
    '''
    Purpose: A fake website client where user 1 ("alice") has the password above.
    '''
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    conn, cur = fake_db(monkeypatch, fetchone=(1, "alice", pw_hash, "test@my.hamptonu.edu", "user", None))
    monkeypatch.setattr(application, "get_db_connection", lambda: conn)
    application._login_attempts.clear()
    return application.app.test_client()


@pytest.fixture
def transfer_spy(monkeypatch):
    '''
    Purpose: Replaces the real transfer so no money moves, but lets a test
             check whether a transfer was attempted.
    '''
    spy = MagicMock(return_value=0)
    monkeypatch.setattr("backend.Wallet.transfer_money", spy)
    return spy


def test_transfer_money_no_password(client, transfer_spy):
    '''
    Purpose: Tests that a transfer sent with no password is rejected and no
             money moves.
    Expected Result: Fail (known bug: the password is only checked in the
                     browser JavaScript, so the server transfers the money anyway)
    '''
    res = client.post("/api/wallet/transfer",
                      json={"buyer_id": 1, "seller_id": 2, "amount": 50})

    assert res.status_code in (400, 401, 403)
    transfer_spy.assert_not_called()


def test_transfer_money_with_password(client, transfer_spy):
    '''
    Purpose: Tests that a transfer goes through after the correct password is
             entered, the same way the wallet page does it (login, then transfer).
    Expected Result: Pass
    '''
    login = client.post("/api/auth/login",
                        json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200

    res = client.post("/api/wallet/transfer",
                      json={"buyer_id": 1, "seller_id": 2, "amount": 50})
    assert res.status_code == 200
    transfer_spy.assert_called_once_with(1, 2, 50.0)


# ---------- get_transaction_history ----------

def test_get_transaction_history(monkeypatch):
    '''
    Purpose: Tests that get_transaction_history turns database rows into
             readable dictionaries (amount as a float).
    Expected Result: Pass
    '''
    rows = [(1, 1, 2, Decimal("50.00"), "purchase", "2026-01-01 10:00:00", "alice", "bob")]
    fake_db(monkeypatch, fetchall=rows)
    assert get_transaction_history(1) == [{
        "id": 1, "from_user_id": 1, "to_user_id": 2, "amount": 50.0,
        "type": "purchase", "created_at": "2026-01-01 10:00:00",
        "from_username": "alice", "to_username": "bob",
    }]


def test_get_transaction_history_empty(monkeypatch):
    '''
    Purpose: Tests that a user with no transactions gets an empty list.
    Expected Result: Pass
    '''
    fake_db(monkeypatch, fetchall=[])
    assert get_transaction_history(1) == []
