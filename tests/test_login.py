import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from application import app, get_db_connection  # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_login_wrong_pass(client):
    res = client.post("/api/auth/login", json={"username": "admin" + uuid.uuid4().hex, "password": "x"})
    assert res.status_code == 401
    assert res.get_json()["error"] == "Invalid credentials"
