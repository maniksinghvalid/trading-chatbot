"""
session_store.py — SQLite-backed conversation persistence (Phase 1, v0).

Uses SQLModel over SQLite; all queries use the ORM (no string-built SQL) to
satisfy T-04-02 (SQL injection via session_id mitigated).

Schema:
  Turn: id (uuid str, PK), session_id (str, indexed), turn_index (int),
        role (str: "user"|"assistant"), content (str), ticker_scope (str|None),
        created_at (datetime).

Functions:
  append_turn(session_id, role, content, ticker=None)
      Persists a new Turn.  turn_index is auto-incremented per session.

  history(session_id, limit=20) -> list[Turn]
      Returns turns for the session ordered oldest-first (turn_index ASC).
      The limit caps the context window sent to the LLM in routes/chat.py.

  list_sessions() -> list[dict]
      Returns one entry per session_id with the first user message as title.
      Shape: [{"session_id": ..., "title": ...}, ...]
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine, select

from src.config import settings

# ---------------------------------------------------------------------------
# SQLModel table
# ---------------------------------------------------------------------------


class Turn(SQLModel, table=True):
    """A single turn (one user or assistant message) in a conversation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(index=True)
    turn_index: int
    role: str  # "user" | "assistant"
    content: str
    ticker_scope: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Engine — bound to settings.database_url; tables created at module load (v0)
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SQLModel.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_turn(
    session_id: str,
    role: str,
    content: str,
    ticker: Optional[str] = None,
) -> Turn:
    """Append a new turn to the conversation.

    The turn_index is computed as (max existing index for the session) + 1,
    or 0 for the first turn.  This avoids a separate sequence table while
    keeping ordering deterministic.

    Args:
        session_id: Opaque identifier for the conversation.
        role: "user" or "assistant".
        content: The raw message text.
        ticker: The active ticker for this turn (may be None for follow-ups).

    Returns:
        The persisted Turn instance.
    """
    with Session(engine) as db:
        # Compute the next turn_index for this session
        statement = (
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index.desc())  # type: ignore[attr-defined]
        )
        last_turn = db.exec(statement).first()
        next_index = (last_turn.turn_index + 1) if last_turn is not None else 0

        turn = Turn(
            session_id=session_id,
            turn_index=next_index,
            role=role,
            content=content,
            ticker_scope=ticker,
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return turn


def history(session_id: str, limit: int = 20) -> list[Turn]:
    """Return up to `limit` turns for the session, oldest first.

    Args:
        session_id: The conversation to look up.
        limit: Maximum number of turns to return (context window cap).

    Returns:
        List of Turn objects ordered by turn_index ascending (oldest first).
    """
    with Session(engine) as db:
        statement = (
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index.asc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        return list(db.exec(statement).all())


def list_sessions() -> list[dict]:
    """Return a summary list of all sessions.

    Each entry contains:
      - session_id: the opaque identifier
      - title: the text of the first user message in the session

    Returns:
        List of dicts, one per unique session_id.
        Sessions with no user messages are omitted from the title lookup;
        in practice every session starts with a user turn.
    """
    with Session(engine) as db:
        # Fetch all turns ordered by session_id then turn_index so we can
        # group and find the first user message per session efficiently in Python.
        statement = select(Turn).order_by(
            Turn.session_id.asc(),  # type: ignore[attr-defined]
            Turn.turn_index.asc(),  # type: ignore[attr-defined]
        )
        all_turns: list[Turn] = list(db.exec(statement).all())

    # Group by session_id and find the first user message as title
    sessions: dict[str, dict] = {}
    for turn in all_turns:
        if turn.session_id not in sessions:
            sessions[turn.session_id] = {
                "session_id": turn.session_id,
                "title": "",
            }
        # Update title only if we haven't found a user message yet
        if sessions[turn.session_id]["title"] == "" and turn.role == "user":
            sessions[turn.session_id]["title"] = turn.content

    return list(sessions.values())
