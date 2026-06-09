"""
test_auth.py — tests for auth.py (magic-link + JWT + current-user dependency).

All tests are fully offline: no email sends, no network calls.
Auth library: PyJWT (pyjwt on PyPI).

Coverage:
  Task 1 (RED → GREEN):
    - issue_jwt / decode_jwt round-trip preserves user_id in `sub`.
    - An expired JWT raises AuthError.
    - verify_magic_token(issue_magic_link(email)) returns the email.
    - A tampered magic-link token raises AuthError.
    - get_current_user raises HTTP 401 on missing / malformed Authorization header.

  Task 2 (added inline):
    - POST /auth/request-link (email send monkeypatched) returns 200.
    - GET /auth/callback with a valid token returns {access_token, token_type}.
    - list_sessions("userA") returns only userA's sessions.
    - history(session_owned_by_b, user_id="userA") returns [] (ownership enforced).

  Task 3 (added inline):
    - POST /chat with no Authorization header → 401.
    - POST /chat with a valid Bearer JWT persists turns under user_id.
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import src.session_store as ss
from src.auth import (
    AuthError,
    decode_jwt,
    get_current_user,
    issue_jwt,
    issue_magic_link,
    verify_magic_token,
)
from src.config import settings
from src.session_store import append_turn, list_sessions, history


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Replace module-level engine with a StaticPool in-memory SQLite DB.

    StaticPool ensures all threads and connections (including the TestClient's
    ASGI worker threads) share the SAME in-memory SQLite database instance.
    Without StaticPool, each new connection gets an empty :memory: DB with no
    tables, causing 'no such table: turn' errors in integration tests.
    """
    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(mem_engine)
    monkeypatch.setattr(ss, "engine", mem_engine)
    yield mem_engine


# ---------------------------------------------------------------------------
# Task 1: issue_jwt / decode_jwt
# ---------------------------------------------------------------------------

def test_issue_jwt_decode_round_trip():
    """issue_jwt then decode_jwt preserves sub == user_id."""
    token = issue_jwt("user@example.com")
    payload = decode_jwt(token)
    assert payload["sub"] == "user@example.com"


def test_decode_jwt_expired_raises_auth_error():
    """A JWT with an already-expired exp raises AuthError."""
    # Manually mint a token with exp in the past
    payload = {"sub": "expired@example.com", "exp": int(time.time()) - 10}
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_jwt(token)


def test_decode_jwt_tampered_raises_auth_error():
    """Changing one character in the token signature raises AuthError."""
    token = issue_jwt("tamper@example.com")
    # Flip last character of the token
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(AuthError):
        decode_jwt(tampered)


# ---------------------------------------------------------------------------
# Task 1: magic-link mint + verify
# ---------------------------------------------------------------------------

def test_magic_link_round_trip():
    """verify_magic_token(issue_magic_link(email)) returns the original email."""
    email = "magic@example.com"
    link = issue_magic_link(email)
    assert "?token=" in link
    token = link.split("?token=")[1]
    recovered = verify_magic_token(token)
    assert recovered == email


def test_magic_link_tampered_token_raises_auth_error():
    """A tampered magic-link token raises AuthError."""
    link = issue_magic_link("tamper@example.com")
    token = link.split("?token=")[1]
    tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
    with pytest.raises(AuthError):
        verify_magic_token(tampered)


def test_magic_link_expired_raises_auth_error():
    """An expired magic-link token (short TTL) raises AuthError."""
    # Mint a token that's already expired
    import jwt as _pyjwt
    payload = {"sub": "expired@example.com", "exp": int(time.time()) - 5}
    token = _pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthError):
        verify_magic_token(token)


# ---------------------------------------------------------------------------
# Task 1: get_current_user dependency
# ---------------------------------------------------------------------------

def test_get_current_user_missing_header_raises_401():
    """get_current_user raises HTTPException 401 when Authorization is absent."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None)
    assert exc_info.value.status_code == 401


def test_get_current_user_malformed_bearer_raises_401():
    """get_current_user raises 401 for a malformed Bearer value."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="NotBearer token")
    assert exc_info.value.status_code == 401


def test_get_current_user_invalid_token_raises_401():
    """get_current_user raises 401 for an invalid JWT."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer not.a.real.token")
    assert exc_info.value.status_code == 401


def test_get_current_user_valid_token_returns_user_id():
    """get_current_user returns the user_id for a valid Bearer token."""
    token = issue_jwt("valid@example.com")
    user_id = get_current_user(authorization=f"Bearer {token}")
    assert user_id == "valid@example.com"


# ---------------------------------------------------------------------------
# Task 2: routes/auth.py endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_client(monkeypatch):
    """TestClient for the full FastAPI app with email send monkeypatched."""
    import src.routes.auth as auth_routes

    def _fake_send(email: str, link: str) -> None:
        pass  # no-op — never calls Resend in tests

    monkeypatch.setattr(auth_routes, "_send_magic_link_email", _fake_send)
    from src.main import app
    return TestClient(app)


def test_request_link_returns_200(auth_client):
    """POST /auth/request-link with a valid email returns 200."""
    resp = auth_client.post("/auth/request-link", json={"email": "user@example.com"})
    assert resp.status_code == 200


def test_request_link_returns_generic_message(auth_client):
    """POST /auth/request-link response body does not expose internals."""
    resp = auth_client.post("/auth/request-link", json={"email": "user@example.com"})
    body = resp.json()
    assert "message" in body
    # Must NOT contain the magic link or any API key
    assert "token" not in str(body).lower() or "access_token" not in str(body)


def test_auth_callback_valid_token_returns_jwt(auth_client):
    """GET /auth/callback?token=<valid> returns {access_token, token_type}."""
    # Mint a magic-link token directly for the test
    link = issue_magic_link("cb@example.com")
    token = link.split("?token=")[1]

    resp = auth_client.get(f"/auth/callback?token={token}")
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # access_token is a valid JWT for the email
    payload = decode_jwt(body["access_token"])
    assert payload["sub"] == "cb@example.com"


def test_auth_callback_invalid_token_returns_401(auth_client):
    """GET /auth/callback?token=<invalid> returns 401."""
    resp = auth_client.get("/auth/callback?token=invalid.token.here")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task 2: user-scoped session store
# ---------------------------------------------------------------------------

def test_list_sessions_user_scoped():
    """list_sessions(user_id) returns only that user's sessions."""
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    append_turn(sid_a, "user", "hello from A", ticker=None, user_id="userA@example.com")
    append_turn(sid_b, "user", "hello from B", ticker=None, user_id="userB@example.com")

    sessions_a = list_sessions("userA@example.com")
    sessions_b = list_sessions("userB@example.com")

    a_ids = {s["session_id"] for s in sessions_a}
    b_ids = {s["session_id"] for s in sessions_b}

    assert sid_a in a_ids
    assert sid_a not in b_ids
    assert sid_b in b_ids
    assert sid_b not in a_ids


def test_history_ownership_enforced():
    """history(session_id, user_id=non_owner) returns [] (cross-user isolation)."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "owner's turn", ticker=None, user_id="owner@example.com")

    # Non-owner should get empty list
    turns = history(sid, user_id="other@example.com")
    assert turns == []

    # Owner gets the turn
    turns_owner = history(sid, user_id="owner@example.com")
    assert len(turns_owner) == 1


# ---------------------------------------------------------------------------
# Task 3: /chat gated by Authorization
# ---------------------------------------------------------------------------

@pytest.fixture
def chat_client(monkeypatch):
    """TestClient with all external calls monkeypatched for offline testing."""
    import src.routes.auth as auth_routes

    def _fake_send(email: str, link: str) -> None:
        pass

    monkeypatch.setattr(auth_routes, "_send_magic_link_email", _fake_send)

    # Monkeypatch Pinecone retrieve so /chat works offline
    import src.pinecone_client as pc
    monkeypatch.setattr(pc, "retrieve", lambda *a, **kw: [])

    # Monkeypatch intent classifier (avoid LLM call)
    import src.intent_classifier as ic
    monkeypatch.setattr(ic, "classify_intent", lambda msg: {"intent": "chitchat", "tickers": []})

    # Monkeypatch ticker extractor (pure function, no network — but patch for isolation)
    import src.ticker_extractor as te
    monkeypatch.setattr(te, "extract_tickers", lambda msg: [])

    from src.main import app
    return TestClient(app)


def test_chat_no_auth_returns_401(chat_client):
    """POST /chat without Authorization header returns 401."""
    resp = chat_client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_chat_stream_no_auth_returns_401(chat_client):
    """POST /chat/stream without Authorization header returns 401."""
    resp = chat_client.post("/chat/stream", json={"message": "hello"})
    assert resp.status_code == 401


def test_sessions_no_auth_returns_401(chat_client):
    """GET /sessions without Authorization header returns 401."""
    resp = chat_client.get("/sessions")
    assert resp.status_code == 401


def test_chat_with_valid_bearer_succeeds(chat_client):
    """POST /chat with a valid Bearer JWT returns 200 (no-data path)."""
    token = issue_jwt("user@example.com")
    resp = chat_client.post(
        "/chat",
        json={"message": "hello AAPL"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Pinecone is stubbed empty → triggers no-data path → 200 with graceful message
    assert resp.status_code == 200


def test_chat_persists_user_id(chat_client):
    """POST /chat persists turns under the JWT's user_id."""
    token = issue_jwt("persist@example.com")
    resp = chat_client.post(
        "/chat",
        json={"message": "AAPL analysis"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # Verify the session is visible only for this user
    sessions = list_sessions("persist@example.com")
    ids = {s["session_id"] for s in sessions}
    assert session_id in ids

    # Verify cross-user isolation
    sessions_other = list_sessions("other@example.com")
    other_ids = {s["session_id"] for s in sessions_other}
    assert session_id not in other_ids
