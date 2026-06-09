"""
test_session_store.py — tests for session_store.py (SQLite conversation persistence).

All tests use an in-memory or temp-file SQLite DB overriding `session_store.engine`
so they are fully isolated and offline.

Test coverage:
  - Turn CRUD: append_turn persists a row; history round-trips it.
  - Ordering: history returns turns in turn_index ascending order.
  - Limit: history respects the limit argument.
  - Multi-session: history only returns turns for the requested session_id.
  - list_sessions: groups by session_id; first user message is the title.
  - Coreference: second turn with no ticker inherits prior ticker_scope from history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel import SQLModel, create_engine, Session

import src.session_store as ss
from src.session_store import Turn, append_turn, history, list_sessions


# ---------------------------------------------------------------------------
# Fixtures — in-memory DB that doesn't touch chat.db
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """
    Replace the module-level engine with an in-memory SQLite engine for each test.
    Recreates all tables fresh so tests don't share state.
    """
    mem_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(mem_engine)
    monkeypatch.setattr(ss, "engine", mem_engine)
    yield mem_engine


# ---------------------------------------------------------------------------
# Turn CRUD tests
# ---------------------------------------------------------------------------

def test_append_turn_persists_row():
    """append_turn writes a row that history() can retrieve."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "bull case for AAPL", ticker="AAPL")

    turns = history(sid)
    assert len(turns) == 1
    t = turns[0]
    assert t.session_id == sid
    assert t.role == "user"
    assert t.content == "bull case for AAPL"
    assert t.ticker_scope == "AAPL"
    assert t.turn_index == 0


def test_append_turn_auto_increments_turn_index():
    """turn_index increments per session starting from 0."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "first message", ticker="AAPL")
    append_turn(sid, "assistant", "first reply", ticker="AAPL")
    append_turn(sid, "user", "follow up", ticker=None)

    turns = history(sid)
    assert [t.turn_index for t in turns] == [0, 1, 2]


def test_history_returns_oldest_first():
    """history() returns turns ordered by turn_index ascending (oldest first)."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "message A", ticker="TSLA")
    append_turn(sid, "assistant", "reply A", ticker="TSLA")
    append_turn(sid, "user", "message B", ticker=None)

    turns = history(sid)
    assert turns[0].content == "message A"
    assert turns[1].content == "reply A"
    assert turns[2].content == "message B"


def test_history_respects_limit():
    """history(limit=N) returns at most N turns."""
    sid = str(uuid.uuid4())
    for i in range(10):
        append_turn(sid, "user", f"message {i}", ticker="MSFT")

    turns = history(sid, limit=3)
    assert len(turns) == 3
    # Should be the 3 most recent (highest turn_index) — or oldest 3 depending on impl.
    # The plan says "oldest-first" and slice 3 step 3.2 says load history(limit=10),
    # so limit is applied after ordering; the slice's purpose is to cap the context window.
    # We assert the returned turns are from the earlier turns (oldest first, up to limit).
    assert turns[0].turn_index == 0
    assert turns[2].turn_index == 2


def test_history_default_limit_20():
    """history() default limit is 20 — returns all turns when fewer than 20 exist."""
    sid = str(uuid.uuid4())
    for i in range(5):
        append_turn(sid, "user", f"msg {i}", ticker="GOOG")

    turns = history(sid)
    assert len(turns) == 5


def test_history_multi_session_isolation():
    """history() only returns turns for the specified session_id."""
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    append_turn(sid_a, "user", "AAPL question", ticker="AAPL")
    append_turn(sid_b, "user", "TSLA question", ticker="TSLA")

    turns_a = history(sid_a)
    turns_b = history(sid_b)

    assert len(turns_a) == 1
    assert turns_a[0].ticker_scope == "AAPL"

    assert len(turns_b) == 1
    assert turns_b[0].ticker_scope == "TSLA"


def test_append_turn_ticker_none():
    """append_turn accepts ticker=None (follow-up turn without ticker context)."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "what about risks?", ticker=None)

    turns = history(sid)
    assert len(turns) == 1
    assert turns[0].ticker_scope is None


def test_turn_has_created_at():
    """Turns have a created_at timestamp."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "test", ticker="AAPL")

    turns = history(sid)
    assert turns[0].created_at is not None


# ---------------------------------------------------------------------------
# list_sessions tests
# ---------------------------------------------------------------------------

def test_list_sessions_groups_by_session_id():
    """list_sessions returns one entry per session_id for the given user."""
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    user = "test@example.com"

    append_turn(sid_a, "user", "bull case for AAPL", ticker="AAPL", user_id=user)
    append_turn(sid_a, "assistant", "Here is the bull case...", ticker="AAPL", user_id=user)
    append_turn(sid_b, "user", "TSLA risks", ticker="TSLA", user_id=user)

    sessions = list_sessions(user)
    session_ids = {s["session_id"] for s in sessions}
    assert sid_a in session_ids
    assert sid_b in session_ids
    assert len(sessions) == 2


def test_list_sessions_title_is_first_user_message():
    """list_sessions uses the first user message as the session title."""
    sid = str(uuid.uuid4())
    user = "test@example.com"
    append_turn(sid, "user", "bull case for AAPL", ticker="AAPL", user_id=user)
    append_turn(sid, "assistant", "AAPL looks strong...", ticker="AAPL", user_id=user)
    append_turn(sid, "user", "what about risks?", ticker=None, user_id=user)

    sessions = list_sessions(user)
    assert len(sessions) == 1
    assert sessions[0]["title"] == "bull case for AAPL"


def test_list_sessions_empty():
    """list_sessions returns an empty list when no sessions exist."""
    sessions = list_sessions("test@example.com")
    assert sessions == []


def test_list_sessions_each_entry_has_required_keys():
    """Each entry returned by list_sessions has session_id and title fields."""
    sid = str(uuid.uuid4())
    user = "test@example.com"
    append_turn(sid, "user", "AAPL analysis", ticker="AAPL", user_id=user)

    sessions = list_sessions(user)
    assert len(sessions) == 1
    entry = sessions[0]
    assert "session_id" in entry
    assert "title" in entry


# ---------------------------------------------------------------------------
# Coreference / ticker inheritance tests
# ---------------------------------------------------------------------------

def test_inherited_ticker_from_history():
    """
    Coreference: when a follow-up turn has no ticker, the caller can retrieve the
    most recent non-null ticker_scope from history.

    This test documents the pattern used in routes/chat.py:
      prior_ticker = next(
          (t.ticker_scope for t in reversed(turns) if t.ticker_scope),
          None
      )
    """
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "bull case for AAPL", ticker="AAPL")
    append_turn(sid, "assistant", "AAPL looks strong...", ticker="AAPL")

    # Follow-up with no ticker
    turns = history(sid, limit=10)
    prior_ticker = next(
        (t.ticker_scope for t in reversed(turns) if t.ticker_scope),
        None,
    )

    assert prior_ticker == "AAPL"


def test_inherited_ticker_none_when_no_prior_ticker():
    """When no prior turn has a ticker_scope, inheritance returns None."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "general market question", ticker=None)

    turns = history(sid, limit=10)
    prior_ticker = next(
        (t.ticker_scope for t in reversed(turns) if t.ticker_scope),
        None,
    )

    assert prior_ticker is None


def test_inherited_ticker_uses_most_recent_non_null():
    """Ticker inheritance picks the MOST recent non-null ticker_scope."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "first question about AAPL", ticker="AAPL")
    append_turn(sid, "assistant", "AAPL reply", ticker="AAPL")
    append_turn(sid, "user", "now about TSLA", ticker="TSLA")
    append_turn(sid, "assistant", "TSLA reply", ticker="TSLA")
    append_turn(sid, "user", "any risks?", ticker=None)

    turns = history(sid, limit=10)
    prior_ticker = next(
        (t.ticker_scope for t in reversed(turns) if t.ticker_scope),
        None,
    )

    # Most recent non-null is TSLA (turn_index 3)
    assert prior_ticker == "TSLA"


# ---------------------------------------------------------------------------
# retrieved_chunk_ids audit column (DB-01)
# ---------------------------------------------------------------------------

def test_retrieved_chunk_ids_round_trips_list():
    """append_turn round-trips a list of chunk IDs through the DB."""
    sid = str(uuid.uuid4())
    chunk_ids = ["AAPL:ANALYSIS:2024-01-15:0", "AAPL:ANALYSIS:2024-01-15:1"]
    append_turn(sid, "user", "bull case for AAPL", ticker="AAPL")
    append_turn(
        sid, "assistant", "AAPL looks strong...", ticker="AAPL",
        retrieved_chunk_ids=chunk_ids,
    )

    turns = history(sid)
    assert len(turns) == 2
    user_turn = turns[0]
    asst_turn = turns[1]
    # User turns should have None (not set)
    assert user_turn.retrieved_chunk_ids is None
    # Assistant turn should have the exact list back
    assert asst_turn.retrieved_chunk_ids == chunk_ids


def test_retrieved_chunk_ids_none_stored_without_error():
    """append_turn with retrieved_chunk_ids=None persists cleanly (no-data path)."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "what's the market doing?", ticker=None)
    append_turn(sid, "assistant", "No data found.", ticker=None, retrieved_chunk_ids=None)

    turns = history(sid)
    assert len(turns) == 2
    assert turns[1].retrieved_chunk_ids is None


def test_retrieved_chunk_ids_empty_list_stored_without_error():
    """append_turn with retrieved_chunk_ids=[] (empty list) persists cleanly."""
    sid = str(uuid.uuid4())
    append_turn(sid, "user", "question", ticker=None)
    append_turn(sid, "assistant", "reply", ticker=None, retrieved_chunk_ids=[])

    turns = history(sid)
    assert turns[1].retrieved_chunk_ids == []
