"""
test_chat_endpoint.py — tests for POST /chat RAG endpoint.

All tests use FastAPI TestClient + monkeypatching so they run fully offline:
  - OpenAI calls are mocked by monkeypatching llm_client.complete
  - Pinecone retrieve is mocked to control chunk data
  - extract_tickers and classify_intent are stubbed so LLM fallback is never hit

Test coverage:
  - Happy path: chunks returned → answer + citations[] + session_id
  - Session ID passthrough: supplied session_id is echoed back
  - No-data path (VERIFY-NODATA): zero chunks → graceful message + citations==[]
  - LLM error path: complete() raises LLMProviderError → HTTP 503
  - Citations built from real chunk metadata only (no fabrication)
  - Ticker auto-resolution (TICK-01): "how is apple doing" → AAPL passed into retrieve
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from src.main import app
from src.auth import issue_jwt
from src.llm_client import LLMProviderError
import src.market_data as market_data
from src.market_data import QuoteUnavailableError
import src.session_store as ss

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_CHUNKS = [
    {
        "id": "AAPL:ANALYSIS:20240101-1200:summary:0",
        "score": 0.92,
        "text": "Apple posted record revenue of $119.6B in Q1 2024, driven by iPhone sales.",
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
    },
    {
        "id": "AAPL:ANALYSIS:20240101-1200:thesis:1",
        "score": 0.87,
        "text": "Strong services segment growth (20% YoY) diversifies revenue away from hardware.",
        "metadata": {
            "schema_version": 1,
            "ticker": "AAPL",
            "company": "Apple Inc.",
            "report_type": "ANALYSIS",
            "generated_date": "20240101",
            "source_path": "TRADE-ANALYSIS-AAPL.md",
            "signal": "Buy",
            "composite_score": 82,
            "section": "thesis",
            "chunk_index": 1,
        },
    },
]

_FAKE_LLM_ANSWER = (
    "AAPL shows strong fundamentals [src:TRADE-ANALYSIS-AAPL.md:20240101]. "
    "Revenue hit $119.6B in Q1 2024 [src:TRADE-ANALYSIS-AAPL.md:20240101]. "
    "This is for educational purposes only and is NOT financial advice."
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Replace module-level engine with a StaticPool in-memory SQLite DB.

    Ensures TestClient ASGI threads share the same in-memory DB with no
    cross-test state leakage.
    """
    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(mem_engine)
    monkeypatch.setattr(ss, "engine", mem_engine)
    yield mem_engine


@pytest.fixture
def client():
    """FastAPI TestClient using the real app instance."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    """Authorization headers with a test JWT for use in authenticated requests."""
    token = issue_jwt("test@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def stub_extractor_and_classifier(monkeypatch):
    """Stub extract_tickers and classify_intent in the chat route so every test
    runs fully offline without triggering LLM calls from those modules.

    Individual tests that want to assert on extractor/classifier behaviour
    can override these stubs via their own monkeypatch calls.
    """
    # Default stubs: return empty (no ticker extracted, factual intent)
    monkeypatch.setattr(
        "src.routes.chat.extract_tickers",
        lambda text: [],
    )
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "factual", "tickers": []},
    )


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------

def test_post_chat_happy_path(client, auth_headers, monkeypatch):
    """POST /chat returns 200 with non-empty message, citations, and session_id."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    resp = client.post("/chat", json={"message": "bull case for AAPL", "ticker": "AAPL"}, headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()

    # Response body fields are present
    assert "message" in data
    assert "citations" in data
    assert "session_id" in data

    # message is non-empty
    assert len(data["message"]) > 0

    # citations[] is populated (one per fake chunk, both have required metadata)
    assert len(data["citations"]) == 2

    # session_id is a non-empty string
    assert isinstance(data["session_id"], str)
    assert len(data["session_id"]) > 0


def test_post_chat_citation_fields(client, auth_headers, monkeypatch):
    """Citations are built from real chunk metadata with all required fields."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    resp = client.post("/chat", json={"message": "what is the signal for AAPL", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    for citation in data["citations"]:
        assert citation["source_path"] == "TRADE-ANALYSIS-AAPL.md"
        assert citation["generated_date"] == "20240101"
        assert citation["ticker"] == "AAPL"
        assert citation["report_type"] == "ANALYSIS"


def test_post_chat_session_id_passthrough(client, auth_headers, monkeypatch):
    """A supplied session_id is echoed back unchanged."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    supplied_id = "test-session-abc-123"
    resp = client.post(
        "/chat",
        json={"message": "tell me about AAPL", "ticker": "AAPL", "session_id": supplied_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == supplied_id


def test_post_chat_new_session_id_minted(client, auth_headers, monkeypatch):
    """When no session_id is supplied, a new uuid4 is minted."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    resp = client.post("/chat", json={"message": "AAPL fundamentals", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    # UUID4 is 36 chars (8-4-4-4-12 with hyphens)
    assert len(sid) == 36
    assert sid.count("-") == 4


# ---------------------------------------------------------------------------
# No-data path tests (VERIFY-NODATA)
# ---------------------------------------------------------------------------

def test_post_chat_no_data_unknown_ticker(client, auth_headers, monkeypatch):
    """Unknown ticker with zero chunks returns graceful message + empty citations."""
    # retrieve returns no chunks for an unknown ticker
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    resp = client.post("/chat", json={"message": "what do you know about ZZZZ", "ticker": "ZZZZ"}, headers=auth_headers)
    assert resp.status_code == 200

    data = resp.json()

    # citations MUST be empty — no fabricated sources (VERIFY-NODATA / T-03-02)
    assert data["citations"] == [], (
        f"Expected empty citations for unknown ticker, got: {data['citations']}"
    )

    # Message must reference the ticker and be graceful (not a crash message)
    assert "ZZZZ" in data["message"]
    assert "don't have stored analysis" in data["message"].lower() or \
           "I don't have" in data["message"]

    # session_id still present
    assert "session_id" in data
    assert len(data["session_id"]) > 0


def test_post_chat_no_data_message_wording(client, auth_headers, monkeypatch):
    """No-data response contains the expected graceful wording."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    resp = client.post("/chat", json={"message": "anything", "ticker": "FAKEXYZ"}, headers=auth_headers)
    assert resp.status_code == 200

    message = resp.json()["message"]
    # Must mention the ticker
    assert "FAKEXYZ" in message
    # Must offer the live market data alternative
    assert "live market data" in message.lower()


def test_post_chat_no_data_no_fabricated_citation(client, auth_headers, monkeypatch):
    """No-data path NEVER includes fabricated citations (T-03-02)."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    resp = client.post("/chat", json={"message": "bull case", "ticker": "NODATA"}, headers=auth_headers)
    assert resp.status_code == 200

    # citations field must be an empty list
    assert resp.json()["citations"] == []


def test_post_chat_no_data_no_ticker_supplied(client, auth_headers, monkeypatch):
    """When no ticker is supplied and retrieve returns [], graceful no-data response."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    resp = client.post("/chat", json={"message": "what stocks should I buy"}, headers=auth_headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["citations"] == []
    # Message should still be graceful (references "the requested ticker")
    assert len(data["message"]) > 0


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------

def test_post_chat_llm_error_returns_503(client, auth_headers, monkeypatch):
    """LLMProviderError from complete() is translated to HTTP 503."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr(
        "src.routes.chat.complete",
        lambda *a, **kw: (_ for _ in ()).throw(LLMProviderError("LLM provider unavailable")),
    )

    resp = client.post("/chat", json={"message": "AAPL", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 503
    # Generic body — no key or stack trace
    assert "unavailable" in resp.json()["detail"].lower()


def test_post_chat_pinecone_error_returns_graceful(client, auth_headers, monkeypatch):
    """Pinecone retrieval failure degrades gracefully (no-data response)."""
    def _failing_retrieve(*a, **kw):
        raise RuntimeError("connection timeout")

    monkeypatch.setattr("src.routes.chat.retrieve", _failing_retrieve)

    resp = client.post("/chat", json={"message": "anything", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Treated as no-data: empty citations
    assert data["citations"] == []
    assert len(data["message"]) > 0


# ---------------------------------------------------------------------------
# TICK-01: Auto ticker resolution tests (slice 6)
# ---------------------------------------------------------------------------


def test_post_chat_auto_ticker_from_message(client, auth_headers, monkeypatch):
    """TICK-01: 'how is apple doing' (no req.ticker) resolves AAPL via extract_tickers.

    The mocked extract_tickers returns ["AAPL"], so the route uses that as the
    effective ticker — even though the request body has no 'ticker' field.
    Asserts that retrieve() is called with ticker="AAPL".
    """
    retrieve_calls: list[dict] = []

    def _capturing_retrieve(text, ticker=None, k=6):
        retrieve_calls.append({"text": text, "ticker": ticker})
        return _FAKE_CHUNKS

    # Override the autouse stub: extract_tickers returns AAPL for this test
    monkeypatch.setattr(
        "src.routes.chat.extract_tickers",
        lambda text: ["AAPL"],
    )
    monkeypatch.setattr("src.routes.chat.retrieve", _capturing_retrieve)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    resp = client.post("/chat", json={"message": "how is apple doing"}, headers=auth_headers)
    assert resp.status_code == 200

    assert len(retrieve_calls) == 1, "retrieve must be called exactly once"
    assert retrieve_calls[0]["ticker"] == "AAPL", (
        f"Expected retrieve called with ticker='AAPL', got {retrieve_calls[0]['ticker']!r}"
    )


def test_post_chat_explicit_ticker_wins_over_extraction(client, auth_headers, monkeypatch):
    """Explicit req.ticker takes precedence over extracted tickers (TICK-01)."""
    retrieve_calls: list[dict] = []

    def _capturing_retrieve(text, ticker=None, k=6):
        retrieve_calls.append({"ticker": ticker})
        return _FAKE_CHUNKS

    # extract_tickers would return NVDA, but explicit ticker is AAPL
    monkeypatch.setattr(
        "src.routes.chat.extract_tickers",
        lambda text: ["NVDA"],
    )
    monkeypatch.setattr("src.routes.chat.retrieve", _capturing_retrieve)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    resp = client.post("/chat", json={"message": "tell me about it", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 200
    assert retrieve_calls[0]["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# QUOTE-01: Intent-gated live quote injection tests (slice 7)
# ---------------------------------------------------------------------------

_FAKE_QUOTE = {
    "price": 189.75,
    "day_change_pct": 1.23,
    "volume": 55_000_000,
    "timestamp": "2026-06-09T14:00:00+00:00",
    "source": "yfinance",
}


def test_post_chat_price_question_calls_quote(client, auth_headers, monkeypatch):
    """POST /chat with 'trading at' intent calls market_data.quote(ticker)."""
    quote_calls: list[str] = []

    def _capturing_quote(ticker: str) -> dict:
        quote_calls.append(ticker)
        return _FAKE_QUOTE

    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["AAPL"])
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "factual", "tickers": ["AAPL"]},
    )
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)
    monkeypatch.setattr(market_data, "quote", _capturing_quote)

    resp = client.post("/chat", json={"message": "what's AAPL trading at?", "ticker": "AAPL"}, headers=auth_headers)
    assert resp.status_code == 200

    assert len(quote_calls) == 1, (
        f"Expected quote() called once for price question, got {len(quote_calls)} calls"
    )
    assert quote_calls[0] == "AAPL"


def test_post_chat_price_question_prompt_contains_live_quote(client, auth_headers, monkeypatch):
    """POST /chat with price intent renders '## Live Quote' in the LLM prompt."""
    captured_messages: list[list] = []

    def _capturing_complete(system, messages):
        captured_messages.extend(messages)
        return _FAKE_LLM_ANSWER

    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["AAPL"])
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "factual", "tickers": ["AAPL"]},
    )
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", _capturing_complete)
    monkeypatch.setattr(market_data, "quote", lambda ticker: _FAKE_QUOTE)

    resp = client.post(
        "/chat", json={"message": "what's AAPL trading at right now?", "ticker": "AAPL"}, headers=auth_headers
    )
    assert resp.status_code == 200

    # The last message (user prompt) must contain the live quote inset
    user_msg = next(m for m in reversed(captured_messages) if m["role"] == "user")
    assert "Live Quote" in user_msg["content"], (
        "LLM prompt must contain '## Live Quote' inset for price questions"
    )


def test_post_chat_outlook_question_does_not_call_quote(client, auth_headers, monkeypatch):
    """POST /chat with 'what's the outlook for AAPL?' does NOT call market_data.quote()."""
    quote_calls: list[str] = []

    def _tracking_quote(ticker: str) -> dict:
        quote_calls.append(ticker)
        return _FAKE_QUOTE

    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["AAPL"])
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "trajectory", "tickers": ["AAPL"]},
    )
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)
    monkeypatch.setattr(market_data, "quote", _tracking_quote)

    resp = client.post(
        "/chat", json={"message": "what's the outlook for AAPL?", "ticker": "AAPL"}, headers=auth_headers
    )
    assert resp.status_code == 200

    assert len(quote_calls) == 0, (
        f"Expected quote() NOT called for outlook question, got {len(quote_calls)} calls"
    )


def test_post_chat_quote_unavailable_degrades_gracefully(client, auth_headers, monkeypatch):
    """QuoteUnavailableError from market_data.quote() does not fail the chat response."""
    def _failing_quote(ticker: str) -> dict:
        raise QuoteUnavailableError("provider down")

    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["AAPL"])
    monkeypatch.setattr(
        "src.routes.chat.classify_intent",
        lambda text: {"intent": "factual", "tickers": ["AAPL"]},
    )
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)
    monkeypatch.setattr(market_data, "quote", _failing_quote)

    resp = client.post(
        "/chat", json={"message": "what's AAPL trading at?", "ticker": "AAPL"}, headers=auth_headers
    )
    # Chat must succeed even when quote provider is down
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert len(data["message"]) > 0


# ---------------------------------------------------------------------------
# 02-08 gap-closure regression tests
# ---------------------------------------------------------------------------

def test_coreference_resolves_most_recent_ticker(client, auth_headers, monkeypatch):
    """MARA -> CLOV -> bare 'stock price' coreferences CLOV, not MARA.

    Regression for UAT test 3: when a user switches from one ticker to another,
    a follow-up with no explicit ticker must inherit the MOST RECENTLY mentioned
    ticker (CLOV), not the stale earlier one (MARA).
    """
    import uuid as _uuid
    session_id = str(_uuid.uuid4())

    # Turn 1: MARA question — retrieve returns MARA chunks, extract_tickers returns MARA
    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["MARA"])
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)
    resp1 = client.post(
        "/chat",
        json={"message": "tell me about MARA", "session_id": session_id},
        headers=auth_headers,
    )
    assert resp1.status_code == 200

    # Turn 2: CLOV question — extract_tickers returns CLOV
    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["CLOV"])
    resp2 = client.post(
        "/chat",
        json={"message": "now tell me about CLOV", "session_id": session_id},
        headers=auth_headers,
    )
    assert resp2.status_code == 200

    # Turn 3: bare "stock price" — no explicit ticker, no extraction result
    retrieve_calls: list[dict] = []

    def _capturing_retrieve(text, ticker=None, k=6):
        retrieve_calls.append({"text": text, "ticker": ticker})
        return _FAKE_CHUNKS

    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: [])
    monkeypatch.setattr("src.routes.chat.retrieve", _capturing_retrieve)
    resp3 = client.post(
        "/chat",
        json={"message": "stock price", "session_id": session_id},
        headers=auth_headers,
    )
    assert resp3.status_code == 200

    assert len(retrieve_calls) == 1, "retrieve must be called exactly once for turn 3"
    assert retrieve_calls[0]["ticker"] == "CLOV", (
        f"Expected coreference to resolve 'CLOV' (most recent ticker), "
        f"got {retrieve_calls[0]['ticker']!r}"
    )


def test_nodata_affirmative_fetches_offered_ticker(client, auth_headers, monkeypatch):
    """AAPL no-data offer -> 'yes' -> AAPL live quote (not a different ticker).

    Regression for UAT test 5: when the bot offered live data for AAPL and the
    user replies 'yes', the quote must be fetched for AAPL — even if some other
    ticker (MARA) happens to have stored data that would otherwise be retrieved.
    """
    import uuid as _uuid
    session_id = str(_uuid.uuid4())

    # Turn 1: AAPL question with no stored data — produces no-data offer persisted
    # with ticker_scope="AAPL" and content containing "live market data"
    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: ["AAPL"])
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])  # no data
    resp1 = client.post(
        "/chat",
        json={"message": "bull case for Apple", "session_id": session_id},
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    assert "live market data" in resp1.json()["message"].lower(), (
        "Expected a no-data offer containing 'live market data'"
    )

    # Turn 2: user replies "yes" — retrieve still empty; quote should be called for AAPL
    quote_calls: list[str] = []

    def _capturing_quote(ticker: str) -> dict:
        quote_calls.append(ticker)
        return _FAKE_QUOTE

    # extract_tickers returns nothing (bare affirmative), retrieve still empty
    monkeypatch.setattr("src.routes.chat.extract_tickers", lambda text: [])
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])
    monkeypatch.setattr(market_data, "quote", _capturing_quote)

    resp2 = client.post(
        "/chat",
        json={"message": "yes", "session_id": session_id},
        headers=auth_headers,
    )
    assert resp2.status_code == 200

    assert len(quote_calls) == 1, (
        f"Expected market_data.quote() called once, got {len(quote_calls)} calls"
    )
    assert quote_calls[0] == "AAPL", (
        f"Expected quote called with 'AAPL' (the offered ticker), got {quote_calls[0]!r}"
    )


# ---------------------------------------------------------------------------
# v1.0 milestone-audit hardening: IDOR — cross-user history must not leak
# ---------------------------------------------------------------------------

def test_post_chat_does_not_leak_other_users_history(client, monkeypatch):
    """User A supplying User B's session_id must NOT load B's prior turns as context.

    Regression for the v1.0 milestone-audit IDOR finding: chat.py loaded
    history(session_id) without user_id, so a guessed/leaked session_id would
    surface another user's conversation in the LLM context window. history() is
    now ownership-scoped (user_id passed), returning [] for a non-owned session.
    """
    from src.auth import issue_jwt

    headers_b = {"Authorization": f"Bearer {issue_jwt('userb@example.com')}"}
    headers_a = {"Authorization": f"Bearer {issue_jwt('usera@example.com')}"}
    shared_session = "shared-session-idor-test"

    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.complete", lambda *a, **kw: _FAKE_LLM_ANSWER)

    # User B writes a distinctive turn into the session.
    resp_b = client.post(
        "/chat",
        json={"message": "USERB_SECRET bull case for MARA", "ticker": "MARA", "session_id": shared_session},
        headers=headers_b,
    )
    assert resp_b.status_code == 200

    # User A reuses B's session_id — capture exactly what reaches the LLM.
    captured_messages: list = []

    def _capturing_complete(system, messages):
        captured_messages.extend(messages)
        return _FAKE_LLM_ANSWER

    monkeypatch.setattr("src.routes.chat.complete", _capturing_complete)

    resp_a = client.post(
        "/chat",
        json={"message": "what is new", "ticker": "MARA", "session_id": shared_session},
        headers=headers_a,
    )
    assert resp_a.status_code == 200

    joined = " ".join(m.get("content", "") for m in captured_messages)
    assert "USERB_SECRET" not in joined, (
        "IDOR: User B's prior turns leaked into User A's LLM context"
    )
