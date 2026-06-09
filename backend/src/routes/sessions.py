"""
routes/sessions.py — Session listing and detail endpoints.

GET /sessions
    Returns a list of sessions owned by the authenticated user, each with
    session_id and the first user message as the session title.
    Shape: [{"session_id": ..., "title": ...}]

GET /sessions/{session_id}
    Returns the turn history for a session as a list of turn dicts.
    Only returns turns if the authenticated user owns the session.
    Shape: [{"role": ..., "content": ..., "created_at": ...}]

Security (AUTH-01 / T-02-03-02):
    Both endpoints require a valid Bearer JWT via Depends(get_current_user).
    Unauthenticated requests receive HTTP 401.
    Per-user isolation: list_sessions() filters by user_id from the JWT;
    history() enforces ownership (non-owner receives an empty list).
    The session_id path parameter reaches the DB via SQLModel parameterized
    queries only — no string-built SQL (T-04-02).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.auth import get_current_user
from src.session_store import history, list_sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
def get_sessions(
    user_id: str = Depends(get_current_user),
) -> list[dict]:
    """List all sessions owned by the authenticated user.

    Returns sessions filtered to the current user's JWT sub (email).
    """
    return list_sessions(user_id)


@router.get("/{session_id}")
def get_session_turns(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> list[dict]:
    """Return the full turn history for a session (ownership enforced).

    Args:
        session_id: The session identifier (from the /chat response).
        user_id: The authenticated user's ID (from the Bearer JWT).

    Returns:
        List of turn dicts with role, content, and created_at fields.
        Returns an empty list when the session_id is unknown or owned by
        a different user (cross-user data never leaked — T-02-03-02).
    """
    turns = history(session_id, user_id=user_id)
    return [
        {
            "role": turn.role,
            "content": turn.content,
            "created_at": turn.created_at.isoformat(),
        }
        for turn in turns
    ]
