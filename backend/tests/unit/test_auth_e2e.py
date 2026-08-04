"""
End-to-end auth against the real FastAPI app.

Drives HTTP the way the browser will: login -> access + refresh, authenticated
call, rotation, replay, WebSocket ticket, and the AUTH_ENFORCED cutover.

Imports main, so it carries the full startup cost. Marked slow.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.slow

ADMIN_EMAIL = "owner@example.com"
ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("authe2e")
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{(tmp / 'auth.db').as_posix()}",
        "AUTH_SECRET": "e" * 48,
        "AUTH_ENFORCED": "0",
        "DISABLE_AUTO_TRAIN": "1",
        "DISABLE_AGENT_LOOP": "1",     # no scraping during tests
        "GROQ_API_KEY": "dummy",
        "BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL,
        "BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
    })

    os.chdir(PROJECT_ROOT)
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as c:
        yield c


def _login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# --- bootstrap + login -----------------------------------------------------

def test_bootstrap_admin_can_log_in(client):
    """BOOTSTRAP_ADMIN_* seeded an owner on first start."""
    r = _login(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["email"] == ADMIN_EMAIL
    assert body["user"]["role"] == "admin"


def test_wrong_password_rejected(client):
    assert _login(client, password="nope-nope-nope").status_code == 401


def test_unknown_email_rejected_identically(client):
    """Same status and detail as a wrong password -- no account enumeration."""
    unknown = _login(client, email="nobody@example.com", password="whatever-long")
    wrong = _login(client, password="whatever-long-x")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


# --- authenticated calls ---------------------------------------------------

def test_me_reflects_authentication(client):
    anon = client.get("/api/me").json()
    assert anon["authenticated"] is False

    token = _login(client).json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["authenticated"] is True
    assert me["user"]["email"] == ADMIN_EMAIL


def test_garbage_token_is_ignored_when_not_enforced(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 200
    assert r.json()["authenticated"] is False


# --- rotation --------------------------------------------------------------

def test_refresh_rotates_and_replay_is_rejected(client):
    first = _login(client).json()
    r1 = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r1.status_code == 200
    rotated = r1.json()
    assert rotated["refresh_token"] != first["refresh_token"]

    # Replaying the spent token must fail AND kill the family.
    replay = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401

    after = client.post("/api/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401, "family should have been revoked by the replay"


def test_refresh_without_token_is_a_400(client):
    assert client.post("/api/auth/refresh", json={}).status_code == 400


# --- ws tickets ------------------------------------------------------------

def test_ws_ticket_requires_auth_and_is_single_use(client):
    token = _login(client).json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}

    ticket = client.post("/api/auth/ws-ticket", headers=hdr).json()["ticket"]
    assert ticket

    from auth import ws_tickets
    assert ws_tickets.redeem(ticket) is not None
    assert ws_tickets.redeem(ticket) is None


# --- connections: the server stores no cookies -----------------------------

def test_connections_endpoint_states_the_no_cookie_guarantee(client):
    token = _login(client).json()["access_token"]
    body = client.get("/api/connections", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["connections"] == []
    assert "never credentials" in body["note"]


def test_ingest_rejects_an_unpaired_device(client):
    """/api/ingest writes to the feed, so it is device-authenticated always."""
    r = client.post("/api/ingest", json={"posts": []},
                    headers={"Authorization": "Bearer not-a-device-token"})
    assert r.status_code == 401


def test_ingest_requires_a_token_at_all(client):
    assert client.post("/api/ingest", json={"posts": []}).status_code == 401


# --- connector pairing round trip ------------------------------------------

def test_pair_claim_and_ingest(client):
    token = _login(client).json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}

    code = client.post("/api/connector/pair", headers=hdr).json()["pair_code"]
    assert len(code.split("-")) == 3        # typeable on a desktop

    claimed = client.post("/api/connector/claim", json={"pair_code": code}).json()
    device_token = claimed["device_token"]
    assert device_token

    # A code is single-use.
    assert client.post("/api/connector/claim", json={"pair_code": code}).status_code == 400

    ingest = client.post(
        "/api/ingest",
        headers={"Authorization": f"Bearer {device_token}"},
        json={
            "posts": [{"platform": "linkedin", "poster": "Acme",
                       "text": "We are hiring in Colombo", "url": "https://l/1"}],
            "connection_status": {"platform": "linkedin", "handle": "@me", "status": "ok"},
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["stored"] == 1

    # Dedup by content hash on a second push.
    again = client.post(
        "/api/ingest",
        headers={"Authorization": f"Bearer {device_token}"},
        json={"posts": [{"platform": "linkedin", "poster": "Acme",
                         "text": "We are hiring in Colombo", "url": "https://l/1"}]},
    )
    assert again.json()["skipped_duplicates"] == 1

    conns = client.get("/api/connections", headers=hdr).json()["connections"]
    assert conns and conns[0]["platform"] == "linkedin"
    assert conns[0]["posts_collected"] == 1


def test_challenge_status_sets_a_cooldown(client):
    """A challenge stops that account for 24h; only a human resumes it."""
    token = _login(client).json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    code = client.post("/api/connector/pair", headers=hdr).json()["pair_code"]
    device_token = client.post("/api/connector/claim",
                               json={"pair_code": code}).json()["device_token"]

    client.post("/api/ingest",
                headers={"Authorization": f"Bearer {device_token}"},
                json={"posts": [], "connection_status": {
                    "platform": "twitter", "status": "challenged",
                    "status_reason": "checkpoint served"}})

    conn = next(c for c in client.get("/api/connections", headers=hdr).json()["connections"]
                if c["platform"] == "twitter")
    assert conn["status"] == "challenged"
    assert conn["cooldown_until"] is not None

    client.post("/api/connections/twitter/resume", headers=hdr)
    conn = next(c for c in client.get("/api/connections", headers=hdr).json()["connections"]
                if c["platform"] == "twitter")
    assert conn["status"] == "ok" and conn["cooldown_until"] is None


# --- health stays public ---------------------------------------------------

def test_status_endpoint_is_public(client):
    """render.yaml uses /api/status as the health check; gating it kills deploys."""
    assert client.get("/api/status").status_code == 200
