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
  - retrieved_chunk_ids: JSON audit column round-trips (None, [], and list).
  - Cross-backend parity: fresh engine (restart simulation) shows sessions persisted.
  - Postgres integration (requires @pytest.mark.postgres + live DATABASE_URL): same
    full turn cycle against a real Postgres instance (skipped without DSN).
"""

from __future__ import annotations

import os
import tempfile
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
    """history(limit=N) returns the MOST RECENT N turns, ordered oldest-first within that window."""
    sid = str(uuid.uuid4())
    for i in range(10):
        append_turn(sid, "user", f"message {i}", ticker="MSFT")

    turns = history(sid, limit=3)
    assert len(turns) == 3
    # Must be the 3 most recent turns (turn_index 7, 8, 9), still returned ASC
    assert turns[0].turn_index == 7
    assert turns[-1].turn_index == 9


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


# ---------------------------------------------------------------------------
# Cross-backend parity (restart simulation) — DB-01
# ---------------------------------------------------------------------------

def _run_full_turn_cycle(db_url: str) -> None:
    """
    Exercise the full append_turn → history → list_sessions cycle including
    user_id and retrieved_chunk_ids, using a fresh engine at the given URL.

    This helper is called once with a temp-file SQLite URL (parity proxy) and
    optionally a second time against a real Postgres URL.  Two engines are
    created sequentially to simulate an application restart — data written on
    the first engine must be visible on the second (proves schema migrates
    cleanly via create_all and that sessions survive a restart).
    """
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    # --- First engine: write data ---
    engine1 = create_engine(db_url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine1)

    sid = str(uuid.uuid4())
    user = "parity@example.com"
    chunk_ids = ["AAPL:ANALYSIS:2024-01-15:0", "AAPL:ANALYSIS:2024-01-15:1"]

    # Monkeypatch the module-level engine for append_turn / history
    orig_engine = ss.engine
    ss.engine = engine1
    try:
        append_turn(sid, "user", "bull case for AAPL", ticker="AAPL", user_id=user)
        append_turn(
            sid, "assistant", "AAPL looks strong...", ticker="AAPL",
            user_id=user, retrieved_chunk_ids=chunk_ids,
        )
    finally:
        ss.engine = orig_engine

    engine1.dispose()

    # --- Second engine (same URL) — simulate restart: data must persist ---
    engine2 = create_engine(db_url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine2)

    ss.engine = engine2
    try:
        turns = history(sid)
        sessions = list_sessions(user)
    finally:
        ss.engine = orig_engine

    engine2.dispose()

    # --- Assertions ---
    assert len(turns) == 2, f"Expected 2 turns after restart, got {len(turns)}"

    user_turn = turns[0]
    asst_turn = turns[1]

    assert user_turn.role == "user"
    assert user_turn.user_id == user
    assert user_turn.ticker_scope == "AAPL"
    assert user_turn.retrieved_chunk_ids is None

    assert asst_turn.role == "assistant"
    assert asst_turn.user_id == user
    assert asst_turn.retrieved_chunk_ids == chunk_ids

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid
    assert sessions[0]["title"] == "bull case for AAPL"


def test_cross_backend_parity_sqlite_restart_simulation():
    """
    Full turn cycle (user_id + retrieved_chunk_ids) persists across a fresh
    engine bound to the same temp-file SQLite URL — simulates application
    restart on the SQLite backend (Postgres parity proxy).

    This is the offline gate for DB-01: proves SQLModel create_all builds the
    schema cleanly and sessions survive between engine instances.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db_url = f"sqlite:///{db_path}"
        _run_full_turn_cycle(db_url)
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass  # Cleanup best-effort


# ---------------------------------------------------------------------------
# Most-recent-N windowing regression tests (02-08 gap closure)
# ---------------------------------------------------------------------------

def test_history_returns_most_recent_when_over_limit():
    """history(limit=N) when session has >N turns returns exactly the last N, ordered ASC.

    Regression test for the oldest-N bug: history() must window the tail of the
    conversation (DESC LIMIT N, then reversed to ASC) so callers see recent context.
    """
    sid = str(uuid.uuid4())
    total = 15
    for i in range(total):
        append_turn(sid, "user", f"turn {i}", ticker="AAPL")

    turns = history(sid, limit=5)
    assert len(turns) == 5
    # Should be turn_index 10..14 in ascending order
    expected_indices = list(range(10, 15))
    assert [t.turn_index for t in turns] == expected_indices


def test_coreference_newest_scope_across_window():
    """Coreference resolves the MOST-RECENTLY referenced ticker even in a >limit session.

    Simulates a conversation longer than the history window where an early turn has
    ticker_scope MARA and a later turn (inside the most-recent window) has CLOV.
    The coreference pattern used in routes/chat.py must yield CLOV, not MARA.
    """
    sid = str(uuid.uuid4())
    limit = 10

    # Turn 0: early MARA mention (will fall outside the window)
    append_turn(sid, "user", "tell me about MARA", ticker="MARA")

    # Turns 1..9: filler turns without ticker_scope, pushing MARA outside window
    for i in range(9):
        append_turn(sid, "assistant", f"reply {i}", ticker=None)

    # Turn 10: recent CLOV mention (inside the most-recent-10 window)
    append_turn(sid, "user", "now tell me about CLOV", ticker="CLOV")

    # Turn 11: follow-up with no ticker (will trigger coreference)
    append_turn(sid, "user", "what's the stock price?", ticker=None)

    # The route uses: next((t.ticker_scope for t in reversed(history(sid, limit=10)) if t.ticker_scope), None)
    recent_turns = history(sid, limit=limit)
    prior_ticker = next(
        (t.ticker_scope for t in reversed(recent_turns) if t.ticker_scope),
        None,
    )

    # CLOV is the most recent non-null ticker_scope in the window
    assert prior_ticker == "CLOV", (
        f"Expected coreference to resolve CLOV (most recent), got {prior_ticker!r}. "
        "This means history() is still returning the OLDEST N turns."
    )


@pytest.mark.postgres
def test_cross_backend_parity_postgres_integration():
    """
    Full turn cycle (user_id + retrieved_chunk_ids) against a real Postgres
    instance — proves the schema migrates cleanly via SQLModel create_all.

    Skipped automatically when DATABASE_URL is not set to a Postgres DSN.
    To run:
        docker compose up -d   (from trading-chatbot/)
        export DATABASE_URL=postgresql+psycopg://chatbot:chatbot@localhost:5432/chatbot
        uv run pytest -m postgres
    """
    db_url = os.environ.get("DATABASE_URL", "")
    assert db_url.startswith("postgresql"), (
        "DATABASE_URL must be a postgresql+psycopg:// DSN for this test"
    )
    _run_full_turn_cycle(db_url)
