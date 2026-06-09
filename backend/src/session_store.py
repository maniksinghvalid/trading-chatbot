"""
session_store.py — SQLite-backed conversation persistence (Phase 2, v1).

Uses SQLModel over SQLite; all queries use the ORM (no string-built SQL) to
satisfy T-04-02 (SQL injection via session_id mitigated).

Schema:
  Turn: id (uuid str, PK), session_id (str, indexed), turn_index (int),
        role (str: "user"|"assistant"), content (str), ticker_scope (str|None),
        user_id (str, indexed), created_at (datetime).

Functions:
  append_turn(session_id, role, content, ticker=None, user_id="")
      Persists a new Turn.  turn_index is auto-incremented per session.

  history(session_id, limit=20, user_id=None) -> list[Turn]
      Returns turns for the session ordered oldest-first (turn_index ASC).
      When user_id is provided, enforces ownership: non-owner gets [].
      The limit caps the context window sent to the LLM in routes/chat.py.

  list_sessions(user_id) -> list[dict]
      Returns one entry per session_id with the first user message as title,
      filtered to turns owned by user_id.
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
    user_id: str = Field(default="", index=True)
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
    user_id: str = "",
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
        user_id: The authenticated user who owns this turn (email, from JWT sub).

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
            user_id=user_id,
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return turn


def history(
    session_id: str,
    limit: int = 20,
    user_id: Optional[str] = None,
) -> list[Turn]:
    """Return up to `limit` turns for the session, oldest first.

    When user_id is provided, ownership is enforced: if the session's turns
    don't belong to that user, an empty list is returned (T-02-03-02 — IDOR
    prevention).  user_id=None preserves the Phase 1 behaviour (no filter).

    Args:
        session_id: The conversation to look up.
        limit: Maximum number of turns to return (context window cap).
        user_id: When provided, only return turns owned by this user.

    Returns:
        List of Turn objects ordered by turn_index ascending (oldest first).
        Returns [] if user_id is provided and the session is owned by another.
    """
    with Session(engine) as db:
        statement = (
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index.asc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        turns: list[Turn] = list(db.exec(statement).all())

    if user_id is not None:
        # Ownership check: any turn in the session must belong to user_id
        owner_turns = [t for t in turns if t.user_id == user_id]
        # If session exists but owned by another user, return []
        if turns and not owner_turns:
            return []
        return owner_turns

    return turns


def list_sessions(user_id: str) -> list[dict]:
    """Return a summary list of sessions owned by user_id.

    Each entry contains:
      - session_id: the opaque identifier
      - title: the text of the first user message in the session

    Args:
        user_id: The authenticated user's ID (email from JWT sub).

    Returns:
        List of dicts, one per unique session_id owned by user_id.
        Sessions with no user messages are omitted from the title lookup;
        in practice every session starts with a user turn.
    """
    with Session(engine) as db:
        # Fetch only this user's turns, ordered for grouping
        statement = (
            select(Turn)
            .where(Turn.user_id == user_id)
            .order_by(
                Turn.session_id.asc(),  # type: ignore[attr-defined]
                Turn.turn_index.asc(),  # type: ignore[attr-defined]
            )
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
