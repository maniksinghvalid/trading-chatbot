"""
routes/sessions.py — Session listing and detail endpoints.

GET /sessions
    Returns a list of all sessions, each with session_id and the first user
    message as the session title.  Shape: [{"session_id": ..., "title": ...}]

GET /sessions/{session_id}
    Returns the turn history for a session as a list of turn dicts.
    Shape: [{"role": ..., "content": ..., "created_at": ...}]

Security note (T-04-01):
    Single-user MVP — no auth/isolation between sessions.  Per-user scoping
    is Phase 2 (AUTH-01).  The session_id path parameter reaches the DB via
    SQLModel parameterized queries only — no string-built SQL (T-04-02).
"""

from __future__ import annotations

from fastapi import APIRouter

from src.session_store import history, list_sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
def get_sessions() -> list[dict]:
    """List all sessions with the first user message as the title."""
    return list_sessions()


@router.get("/{session_id}")
def get_session_turns(session_id: str) -> list[dict]:
    """Return the full turn history for a session.

    Args:
        session_id: The session identifier (from the /chat response).

    Returns:
        List of turn dicts with role, content, and created_at fields.
        Returns an empty list when the session_id is unknown.
    """
    turns = history(session_id)
    return [
        {
            "role": turn.role,
            "content": turn.content,
            "created_at": turn.created_at.isoformat(),
        }
        for turn in turns
    ]
