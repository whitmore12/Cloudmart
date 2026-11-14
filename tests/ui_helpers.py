"""Shared helpers for the browser tests. This is not a test module.

Setup:    pip install pytest playwright   then   playwright install chromium
          Set CLOUDMART_TEST_CHROME to use a Chrome that is already installed.
Design:   the real HTML pages are served from the Frontend folder, and every
          /api call is answered by a fake, so no database is needed here.

Author: Claude (Anthropic)
"""

import functools
import http.server
import json
import os
import re
import threading

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Frontend")
USER = {"id": 1, "username": "monster", "role": "user", "email": "m@my.hamptonu.edu"}

def start_server():
    """Serve the Frontend folder on a free port. Returns (server, base_url)."""
    class quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(quiet, directory=FRONTEND)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%s" % server.server_address[1]

def launch(playwright):
    """Start headless Chromium."""
    path = os.getenv("CLOUDMART_TEST_CHROME")
    if path:
        return playwright.chromium.launch(executable_path=path, args=["--no-sandbox"])
    return playwright.chromium.launch(args=["--no-sandbox"])

def fake_backend(page):
    """Answer every /api call with a harmless default. Tests add more specific routes afterwards."""
    def anything(route):
        if "/api/wishlist" in route.request.url:
            body = "[]"
        else:
            body = json.dumps({"balance": 100, "pirate_dollars": 100, "count": 0})
        route.fulfill(status=200, content_type="application/json", body=body)
    page.route(re.compile(r".*/api/.*"), anything)

def sign_in(page, cart=None):
    """Seed a signed-in user, and optionally a cart, on the first page load only."""
    script = "if(!sessionStorage.getItem('seeded')){sessionStorage.setItem('seeded','1');localStorage.setItem('user',%s);" % json.dumps(json.dumps(USER))
    if cart is not None:
        script += "localStorage.setItem('cart',%s);" % json.dumps(json.dumps(cart))
    script += "}"
    page.add_init_script(script)

def item(id, title, price, category="Books", condition="New", seller="pam", size=None, fit=None, status="active"):
    """Build one fake listing as the API would return it."""
    return {"id": id, "user_id": 2, "title": title, "price": price, "category": category,
            "condition": condition, "image": "", "seller": seller, "status": status,
            "buyer_email": None, "size": size, "fit": fit}
