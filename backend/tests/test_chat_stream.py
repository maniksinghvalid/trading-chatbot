"""
test_chat_stream.py — tests for POST /chat/stream SSE endpoint (slice 4).

All tests run fully offline:
  - stream_complete is mocked to yield a controlled list of token chunks
  - Pinecone retrieve is mocked to control chunk data
  - Session store uses a temp-file SQLite fixture for test isolation.
    NOTE: SQLite in-memory databases (sqlite:///:memory:) are connection-scoped —
    each new connection opens a fresh empty DB, so cross-thread access (as happens
    in sse_starlette's ASGI runner) sees a different, empty database.  A temp-file
    DB with check_same_thread=False is used instead; the file is deleted after
    each test.

Test coverage:
  - Event ORDER: session -> citations -> token* -> done
  - Citations emitted ONCE, up front (before any token)
  - Both user and assistant turns persisted on completion
  - No-data path: graceful message token + both turns persisted + no citations
  - Mid-stream LLMProviderError: terminating error event then done, no key leakage
  - Session ID passthrough: supplied session_id echoed in session event
  - New session_id minted when none supplied
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

import src.session_store as ss
from sqlmodel import create_engine
from sqlmodel import SQLModel

from src.main import app
from src.llm_client import LLMProviderError
from src.session_store import history as get_history

# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

_FAKE_CHUNKS = [
    {
        "id": "AAPL:ANALYSIS:20240101-1200:summary:0",
        "score": 0.92,
        "text": "Apple posted record revenue of $119.6B in Q1 2024.",
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
]

_FAKE_TOKENS = ["Hello", " world", " from", " AAPL", " analysis"]


def _make_stream_mock(tokens: list[str]):
    """Return a function that replaces stream_complete, yielding the given tokens."""
    def _mock_stream_complete(system, messages):
        yield from tokens
    return _mock_stream_complete


def _make_stream_error_mock():
    """Return a stream_complete mock that raises LLMProviderError mid-stream."""
    def _mock_stream_error(system, messages):
        yield "partial token"
        raise LLMProviderError("LLM provider unavailable")
    return _mock_stream_error


def _parse_sse_events(body: bytes) -> list[dict]:
    """Parse an SSE response body into a list of {event, data} dicts.

    Handles the text/event-stream format: blocks separated by blank lines,
    each block containing optional `event:` and `data:` lines.

    The SSE spec says the field value starts immediately after the ": " separator.
    We strip trailing whitespace from field names but preserve the data value
    exactly (including leading spaces, which are significant for token events
    that yield " world"-style tokens).
    """
    events = []
    current: dict = {}
    for raw_line in body.decode("utf-8").splitlines():
        # Strip only trailing whitespace; preserve leading content
        line = raw_line.rstrip()
        if line.startswith("event:"):
            # "event: session" -> strip both sides for event name
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            # "data:  world" -> remove "data:" prefix and exactly one space (if present)
            raw_val = line[len("data:"):]
            current["data"] = raw_val[1:] if raw_val.startswith(" ") else raw_val
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


@pytest.fixture
def file_engine(monkeypatch):
    """Replace the session_store engine with an isolated temp-file SQLite engine.

    SQLite's :memory: database is connection-scoped; sse_starlette's ASGI runner
    opens new connections in worker threads and would see an empty DB.  A temp
    file with check_same_thread=False is visible across all connections.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(ss, "engine", test_engine)
    yield test_engine
    # Cleanup: dispose connections then remove the temp file
    test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client(file_engine):
    """TestClient using the real app with an isolated temp-file session store."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Event order tests
# ---------------------------------------------------------------------------

def test_stream_event_order(client, monkeypatch):
    """SSE events must arrive in order: session -> citations -> token* -> done."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "bull case for AAPL", "ticker": "AAPL"},
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.content)
    event_names = [e["event"] for e in events if "event" in e]

    # Must have all four event types
    assert "session" in event_names
    assert "citations" in event_names
    assert "token" in event_names
    assert "done" in event_names

    # Verify strict ordering: session first, citations second, tokens in middle, done last
    first_idx = event_names.index("session")
    citations_idx = event_names.index("citations")
    first_token_idx = event_names.index("token")
    done_idx = event_names.index("done")

    assert first_idx == 0, "session must be the first event"
    assert citations_idx == 1, "citations must be the second event (index 1)"
    assert citations_idx < first_token_idx, "citations must arrive before any token"
    assert first_token_idx < done_idx, "tokens must arrive before done"
    assert done_idx == len(event_names) - 1, "done must be the last event"


def test_stream_citations_once_before_tokens(client, monkeypatch):
    """Citations must be emitted exactly ONCE, up front, before any token event."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL analysis", "ticker": "AAPL"},
    )
    events = _parse_sse_events(resp.content)
    event_names = [e["event"] for e in events if "event" in e]

    # Citations appears exactly once
    assert event_names.count("citations") == 1

    # The citations event comes before all token events
    citations_idx = event_names.index("citations")
    token_indices = [i for i, name in enumerate(event_names) if name == "token"]
    assert all(citations_idx < ti for ti in token_indices), (
        "citations event must precede every token event"
    )


def test_stream_tokens_carry_content(client, monkeypatch):
    """Token events carry the expected text payload from stream_complete."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL"},
    )
    events = _parse_sse_events(resp.content)
    token_events = [e for e in events if e.get("event") == "token"]
    token_data = [e["data"] for e in token_events]

    assert token_data == _FAKE_TOKENS


# ---------------------------------------------------------------------------
# Turn persistence tests
# ---------------------------------------------------------------------------

def test_stream_both_turns_persisted(client, monkeypatch):
    """After stream completes, both user and assistant turns are in the session store."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "bull case for AAPL", "ticker": "AAPL", "session_id": "stream-persist-test"},
    )
    assert resp.status_code == 200

    turns = get_history("stream-persist-test")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "bull case for AAPL"
    assert turns[1].role == "assistant"
    assert turns[1].content == "".join(_FAKE_TOKENS)


def test_stream_assistant_text_is_full_concatenation(client, monkeypatch):
    """Persisted assistant turn content is the full concatenation of all tokens."""
    tokens = ["The ", "bull ", "case ", "is ", "strong."]
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(tokens))

    session_id = "concat-test-session"
    resp = client.post(
        "/chat/stream",
        json={"message": "any question", "ticker": "AAPL", "session_id": session_id},
    )
    assert resp.status_code == 200

    turns = get_history(session_id)
    assistant_turns = [t for t in turns if t.role == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0].content == "The bull case is strong."


def test_stream_turns_queryable_via_sessions_endpoint(client, monkeypatch):
    """GET /sessions/{id} reflects turns persisted by the stream endpoint."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    session_id = "sessions-check-test"
    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL question", "ticker": "AAPL", "session_id": session_id},
    )
    assert resp.status_code == 200

    detail = client.get(f"/sessions/{session_id}")
    assert detail.status_code == 200
    turns = detail.json()
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# No-data path tests
# ---------------------------------------------------------------------------

def test_stream_no_data_emits_graceful_token(client, monkeypatch):
    """Zero-chunk path emits session, citations (empty), graceful token, done — no tokens from LLM."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    resp = client.post(
        "/chat/stream",
        json={"message": "what about ZZZZ", "ticker": "ZZZZ"},
    )
    events = _parse_sse_events(resp.content)
    event_names = [e["event"] for e in events if "event" in e]

    assert "session" in event_names
    assert "citations" in event_names
    assert "token" in event_names
    assert "done" in event_names
    assert event_names.count("citations") == 1

    # Citations is empty JSON array
    citations_event = next(e for e in events if e.get("event") == "citations")
    assert json.loads(citations_event["data"]) == []

    # The graceful message mentions the ticker
    token_event = next(e for e in events if e.get("event") == "token")
    assert "ZZZZ" in token_event["data"]


def test_stream_no_data_turns_persisted(client, monkeypatch):
    """No-data path still persists both user and assistant turns."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: [])

    session_id = "no-data-stream-session"
    resp = client.post(
        "/chat/stream",
        json={"message": "anything about FAKEXYZ", "ticker": "FAKEXYZ", "session_id": session_id},
    )
    assert resp.status_code == 200

    turns = get_history(session_id)
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    assert "FAKEXYZ" in turns[1].content


# ---------------------------------------------------------------------------
# Error handling tests (T-05-02)
# ---------------------------------------------------------------------------

def test_stream_llm_error_emits_error_event_then_done(client, monkeypatch):
    """LLMProviderError mid-stream emits error event then done — no crash, no key leak."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_error_mock())

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL"},
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.content)
    event_names = [e["event"] for e in events if "event" in e]

    # Must have both error and done
    assert "error" in event_names, f"Expected error event, got: {event_names}"
    assert "done" in event_names

    # done must come after error
    error_idx = event_names.index("error")
    done_idx = event_names.index("done")
    assert error_idx < done_idx, "error event must precede done"

    # Error message is generic — no key or stack trace
    error_event = next(e for e in events if e.get("event") == "error")
    assert "unavailable" in error_event["data"].lower()
    assert "key" not in error_event["data"].lower()
    assert "traceback" not in error_event["data"].lower()


def test_stream_llm_error_emits_session_and_citations_before_error(client, monkeypatch):
    """Even on LLM error, session and citations events are emitted before error/done."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_error_mock())

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL"},
    )
    events = _parse_sse_events(resp.content)
    event_names = [e["event"] for e in events if "event" in e]

    assert event_names[0] == "session"
    assert event_names[1] == "citations"


# ---------------------------------------------------------------------------
# Session ID tests
# ---------------------------------------------------------------------------

def test_stream_session_id_passthrough(client, monkeypatch):
    """Supplied session_id is returned in the session event."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    supplied_id = "my-custom-session-id"
    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL", "session_id": supplied_id},
    )
    events = _parse_sse_events(resp.content)
    session_event = next(e for e in events if e.get("event") == "session")
    assert session_event["data"] == supplied_id


def test_stream_new_session_id_minted(client, monkeypatch):
    """When no session_id supplied, a UUID4 is minted and returned in session event."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL"},
    )
    events = _parse_sse_events(resp.content)
    session_event = next(e for e in events if e.get("event") == "session")
    sid = session_event["data"]
    # UUID4 is 36 characters with 4 hyphens
    assert len(sid) == 36
    assert sid.count("-") == 4


# ---------------------------------------------------------------------------
# Citations content tests
# ---------------------------------------------------------------------------

def test_stream_citations_content(client, monkeypatch):
    """Citations event carries the expected Citation fields from chunk metadata."""
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post(
        "/chat/stream",
        json={"message": "AAPL", "ticker": "AAPL"},
    )
    events = _parse_sse_events(resp.content)
    citations_event = next(e for e in events if e.get("event") == "citations")
    citations = json.loads(citations_event["data"])

    assert len(citations) == 1
    c = citations[0]
    assert c["source_path"] == "TRADE-ANALYSIS-AAPL.md"
    assert c["generated_date"] == "20240101"
    assert c["ticker"] == "AAPL"
    assert c["report_type"] == "ANALYSIS"
