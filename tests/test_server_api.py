"""TDD spec for the HTTP API contract on /api/message.

Two ergonomics guarantees the front end and any scripted client rely on:
  * `text` works as an alias for `message` (both name the user's turn).
  * a missing/unknown `session_id` auto-starts a session instead of 404-ing,
    and the new id is returned so the caller can keep using it.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.server import app

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")
pytestmark = pytest.mark.skipif(not os.path.exists(ASSET), reason="1040 template missing")

client = TestClient(app)


def test_message_accepts_text_alias():
    sid = client.post("/api/session").json()["session_id"]
    r = client.post("/api/message",
                    json={"session_id": sid, "text": "Box 1 wages 42000, Box 2 withholding 4200"})
    assert r.status_code == 200
    assert r.json()["phase"] == "confirm_w2"


def test_message_autostarts_session_when_missing():
    r = client.post("/api/message",
                    json={"message": "Box 1 wages 42000, Box 2 withholding 4200"})
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "confirm_w2"
    # the freshly created id comes back so the client can reuse it
    assert body.get("session_id")


def test_autostarted_session_id_is_reusable():
    first = client.post("/api/message",
                        json={"message": "Box 1 wages 42000, Box 2 withholding 4200"}).json()
    sid = first["session_id"]
    second = client.post("/api/message", json={"session_id": sid, "text": "yes"})
    assert second.status_code == 200
    assert second.json()["phase"] == "filing_status"
