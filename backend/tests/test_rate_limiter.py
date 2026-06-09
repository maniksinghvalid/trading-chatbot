"""
test_rate_limiter.py — tests for UserBudget table + check_and_increment + HTTP 429 gate.

All tests run fully offline. The clock is injected via monkeypatching rate_limiter._now
so midnight-UTC reset and retry-after assertions are deterministic.

Coverage:
  Task 1 — Unit: UserBudget table + check_and_increment
    - Happy path: first N requests succeed
    - Request-budget exceeded: (N+1)-th call raises BudgetExceeded with retry_after_seconds > 0
    - Token-budget exceeded: input_tokens accumulation trips BudgetExceeded
    - Midnight-UTC reset: row dated yesterday resets to request_count==1 (no raise)
    - retry_after_seconds: equals seconds to next midnight UTC under patched clock
    - current_usage: returns per-user row dicts

  Task 2 — Integration: /chat + /chat/stream return 429 + Retry-After
    - (budget+1)-th POST /chat returns 429 with numeric Retry-After header
    - A fresh user (different user_id) within budget still gets 200
    - POST /chat/stream returns 429 HTTP response (not SSE) when over budget

  Task 3 — Integration: GET /admin/budgets
    - Correct admin token returns per-user usage including request_count
    - Missing/wrong admin token returns 401
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import src.rate_limiter as rl
import src.session_store as ss
from src.auth import issue_jwt
from src.config import settings
from src.main import app
from src.rate_limiter import BudgetExceeded, UserBudget, check_and_increment, current_usage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Give every test its own in-memory SQLite with both SQLModel tables.

    Patches both session_store.engine and rate_limiter.engine to the same
    in-memory StaticPool DB so TestClient ASGI threads share the state.
    """
    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(mem_engine)
    monkeypatch.setattr(ss, "engine", mem_engine)
    monkeypatch.setattr(rl, "engine", mem_engine)
    yield mem_engine


@pytest.fixture(autouse=True)
def stub_extractor_and_classifier(monkeypatch):
    """Stub extract_tickers and classify_intent in chat route — offline only."""
    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: [])
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "factual", "tickers": []},
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers_a() -> dict:
    """Authorization headers for user A."""
    token = issue_jwt("user_a@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_b() -> dict:
    """Authorization headers for user B (different user — within budget)."""
    token = issue_jwt("user_b@example.com")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Task 1: Unit tests — UserBudget + check_and_increment
# ---------------------------------------------------------------------------


def test_happy_path_requests_within_budget(monkeypatch):
    """First (budget) calls to check_and_increment succeed without raising."""
    monkeypatch.setattr(settings, "daily_request_budget", 3)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    for _ in range(3):
        # Should not raise
        check_and_increment("happy@example.com")


def test_request_budget_exceeded_raises(monkeypatch):
    """The (budget+1)-th call raises BudgetExceeded."""
    monkeypatch.setattr(settings, "daily_request_budget", 2)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    check_and_increment("exceed@example.com")
    check_and_increment("exceed@example.com")

    with pytest.raises(BudgetExceeded) as exc_info:
        check_and_increment("exceed@example.com")

    assert exc_info.value.retry_after_seconds > 0


def test_token_budget_exceeded_raises(monkeypatch):
    """input_token_count accumulation triggers BudgetExceeded on token cap."""
    monkeypatch.setattr(settings, "daily_request_budget", 1000)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100)

    # 90 tokens — fine
    check_and_increment("tokens@example.com", input_tokens=90)
    # 20 more would exceed cap of 100
    with pytest.raises(BudgetExceeded):
        check_and_increment("tokens@example.com", input_tokens=20)


def test_midnight_utc_reset(monkeypatch):
    """A row dated yesterday UTC resets to request_count==1 on next call (no raise)."""
    monkeypatch.setattr(settings, "daily_request_budget", 1)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    user_id = "reset@example.com"

    # Use a fixed "yesterday" date to pre-populate the row
    yesterday = date(2026, 6, 8)
    today = date(2026, 6, 9)

    # Manually insert a row dated yesterday with request_count at the limit
    with Session(rl.engine) as db:
        row = UserBudget(
            user_id=user_id,
            usage_date=yesterday,
            request_count=1,  # already at the limit
            input_token_count=0,
        )
        db.add(row)
        db.commit()

    # Patch _now to return "today"
    fixed_dt = datetime(2026, 6, 9, 8, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(rl, "_now", lambda: fixed_dt)

    # Should NOT raise — it's a new day, so the count resets
    check_and_increment(user_id)

    # Verify request_count is 1 (reset to 1, not 0 then incremented)
    with Session(rl.engine) as db:
        row = db.get(UserBudget, user_id)
    assert row is not None
    assert row.usage_date == today
    assert row.request_count == 1


def test_retry_after_seconds_equals_seconds_to_next_midnight(monkeypatch):
    """retry_after_seconds matches seconds to next UTC midnight under patched clock."""
    monkeypatch.setattr(settings, "daily_request_budget", 1)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    user_id = "retryafter@example.com"

    # Patch clock to 23:00:00 UTC on 2026-06-09
    fixed_dt = datetime(2026, 6, 9, 23, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(rl, "_now", lambda: fixed_dt)

    # Exhaust the budget
    check_and_increment(user_id)

    with pytest.raises(BudgetExceeded) as exc_info:
        check_and_increment(user_id)

    # Next midnight UTC = 2026-06-10 00:00:00 UTC → 3600 seconds away
    expected = 3600
    assert exc_info.value.retry_after_seconds == expected, (
        f"Expected retry_after_seconds={expected}, got {exc_info.value.retry_after_seconds}"
    )


def test_current_usage_returns_list_for_all_users(monkeypatch):
    """current_usage(user_id=None) returns a list containing all active users."""
    monkeypatch.setattr(settings, "daily_request_budget", 10)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    check_and_increment("alice@example.com")
    check_and_increment("alice@example.com")
    check_and_increment("bob@example.com")

    result = current_usage()
    assert isinstance(result, list)
    user_ids = {r["user_id"] for r in result}
    assert "alice@example.com" in user_ids
    assert "bob@example.com" in user_ids

    alice_row = next(r for r in result if r["user_id"] == "alice@example.com")
    assert alice_row["request_count"] == 2


def test_current_usage_per_user(monkeypatch):
    """current_usage(user_id=X) returns a single dict for user X."""
    monkeypatch.setattr(settings, "daily_request_budget", 10)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)

    check_and_increment("carol@example.com")
    result = current_usage("carol@example.com")
    assert isinstance(result, dict)
    assert result["user_id"] == "carol@example.com"
    assert result["request_count"] == 1


# ---------------------------------------------------------------------------
# Task 2: Integration tests — /chat + /chat/stream 429 gate
# ---------------------------------------------------------------------------

_FAKE_CHUNKS = [
    {
        "id": "AAPL:ANALYSIS:20240101-1200:summary:0",
        "score": 0.92,
        "text": "Apple revenue.",
        "metadata": {
            "schema_version": 1,
            "ticker": "AAPL",
            "company": "Apple Inc.",
            "report_type": "ANALYSIS",
            "generated_date": "20240101",
            "source_path": "TRADE-ANALYSIS-AAPL.md",
            "signal": "Buy",
            "composite_score": 82,
            "section": "summary",
            "chunk_index": 0,
        },
    }
]

_FAKE_LLM_ANSWER = "AAPL analysis. Not financial advice."


def test_post_chat_429_after_budget_exceeded(client, auth_headers_a, monkeypatch):
    """The (budget+1)-th POST /chat for a user returns 429 with Retry-After header."""
    monkeypatch.setattr(settings, "daily_request_budget", 2)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    # First 2 requests should succeed
    for _ in range(2):
        resp = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_a)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    # 3rd request should be rejected
    resp = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_a)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    # Retry-After must be a numeric string
    retry_after = resp.headers["Retry-After"]
    assert retry_after.isdigit(), f"Expected numeric Retry-After, got {retry_after!r}"
    assert int(retry_after) > 0


def test_post_chat_different_user_within_budget(client, auth_headers_a, auth_headers_b, monkeypatch):
    """A different authenticated user within budget still gets 200."""
    monkeypatch.setattr(settings, "daily_request_budget", 1)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    # Exhaust user_a's budget
    resp_a = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_a)
    assert resp_a.status_code == 200
    resp_a2 = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_a)
    assert resp_a2.status_code == 429

    # user_b should still succeed
    resp_b = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_b)
    assert resp_b.status_code == 200


def test_post_chat_stream_429_before_sse(client, auth_headers_a, monkeypatch):
    """POST /chat/stream returns a 429 HTTP response (not an SSE event) when over budget."""
    monkeypatch.setattr(settings, "daily_request_budget", 1)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)

    # Exhaust the budget
    resp = client.post("/chat", json={"message": "AAPL?"}, headers=auth_headers_a)
    assert resp.status_code == 200

    # Stream request should get a proper 429, not an SSE stream starting
    resp_stream = client.post("/chat/stream", json={"message": "AAPL?"}, headers=auth_headers_a)
    assert resp_stream.status_code == 429
    assert "Retry-After" in resp_stream.headers


# ---------------------------------------------------------------------------
# Task 3: Integration tests — GET /admin/budgets
# ---------------------------------------------------------------------------


def test_admin_budgets_returns_usage_with_correct_token(client, monkeypatch):
    """GET /admin/budgets with correct X-Admin-Token returns per-user usage."""
    monkeypatch.setattr(settings, "daily_request_budget", 10)
    monkeypatch.setattr(settings, "daily_input_token_budget", 100_000)
    monkeypatch.setattr(settings, "admin_token", "test-admin-secret")

    # Create some usage
    check_and_increment("admintest@example.com")
    check_and_increment("admintest@example.com")

    resp = client.get("/admin/budgets", headers={"X-Admin-Token": "test-admin-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    user_row = next((r for r in data if r["user_id"] == "admintest@example.com"), None)
    assert user_row is not None
    assert user_row["request_count"] == 2


def test_admin_budgets_wrong_token_returns_401(client, monkeypatch):
    """GET /admin/budgets with wrong admin token returns 401."""
    monkeypatch.setattr(settings, "admin_token", "real-secret")

    resp = client.get("/admin/budgets", headers={"X-Admin-Token": "wrong-secret"})
    assert resp.status_code == 401


def test_admin_budgets_missing_token_returns_401(client):
    """GET /admin/budgets with no X-Admin-Token header returns 401."""
    resp = client.get("/admin/budgets")
    assert resp.status_code == 401
