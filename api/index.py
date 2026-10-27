"""Vercel Python function entrypoint for the CloudMart Flask app."""

from app import app as flask_app

app = flask_app
handler = flask_app
