"""
routes/admin.py — Admin endpoints for operational visibility.

GET /admin/budgets
    Returns per-user daily usage from the UserBudget table.
    Accepts an optional ``?user_id=`` query parameter to filter to a single user.

Security (T-02-05-02):
    The endpoint is gated by an ``X-Admin-Token`` header check.  The token must
    match ``settings.admin_token`` (set ADMIN_TOKEN in the environment).
    A missing or incorrect token yields HTTP 401 — no usage data is leaked.
    This is intentionally minimal (no full RBAC) per the plan scope.

    Admin-token header is NOT logged and not included in error responses so the
    token is not accidentally leaked to client-visible error messages.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from src.config import settings
from src.rate_limiter import current_usage

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Dependency: verify the X-Admin-Token header (T-02-05-02).

    Raises:
        HTTPException(401): When the header is absent or does not match
                            ``settings.admin_token``.  No token value is
                            included in the error response (no secret leakage).
    """
    if x_admin_token is None or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/budgets")
def get_budgets(
    user_id: Optional[str] = None,
    _admin: None = None,
    x_admin_token: Optional[str] = Header(default=None),
) -> list[dict] | dict:
    """Return per-user daily budget usage.

    Args:
        user_id: Optional query parameter to filter to a single user.
        x_admin_token: The admin token from the ``X-Admin-Token`` request header.

    Returns:
        When ``user_id`` is supplied: a dict with the user's current usage.
        When ``user_id`` is absent: a list of dicts for all users with any
        budget row (including those who haven't made requests today — they
        won't appear, as rows are only created on first request).

    Raises:
        HTTPException(401): On missing or incorrect ``X-Admin-Token``.
    """
    # Guard: verify admin token
    if x_admin_token is None or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return current_usage(user_id)
