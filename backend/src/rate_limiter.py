"""
rate_limiter.py — Per-user daily budget tracking with midnight-UTC reset (slice 10 / RATE-01).

Tracks two dimensions per user per day:
  - request_count: number of chat requests (mapped to turns; caps spend on long-session abuse)
  - input_token_count: cumulative OpenAI input tokens (direct LLM cost ceiling)

A single `UserBudget` SQLModel table stores one row per user_id (primary key).
The row is reset when `usage_date` does not match today UTC, ensuring a fresh
budget window at midnight UTC regardless of how long the server has been running.

Public API:
  check_and_increment(user_id, input_tokens=0) -> None
      Gate for every /chat + /chat/stream call. Resets the row if it is stale
      (yesterday or earlier), then increments counts. Raises `BudgetExceeded`
      (carrying `retry_after_seconds` = seconds to next midnight UTC) when either
      cap is exceeded — BEFORE incrementing, so the budget is precise.

  current_usage(user_id=None) -> list[dict] | dict
      Read-only view for /admin/budgets. Returns all rows as a list when
      user_id is None, or a single dict for a specific user.

  BudgetExceeded(RuntimeError)
      Raised when a user exceeds their daily request or input-token cap.
      Carries `retry_after_seconds` (int) — seconds until the next UTC midnight.

Security:
  T-02-05-01: LLM cost runaway — request + token caps enforced per-user each day.
  T-02-05-03: Budget bypass — user_id is taken from the JWT (02-03); callers must
              pass the authenticated user_id, never a request-body value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine, select

from src.config import settings
from src.session_store import engine  # reuse the same engine (same DB)

# Re-export the shared engine so tests can monkeypatch it uniformly.
# This module holds a module-level reference; tests patch `src.rate_limiter.engine`.
engine = engine  # noqa: F811 — explicit re-export to make monkeypatching clean


# ---------------------------------------------------------------------------
# Clock helper — factored so tests can patch the clock
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return the current UTC datetime. Patchable by tests."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    """Raised when the per-user daily budget is exhausted.

    Attributes:
        retry_after_seconds: Seconds until the next UTC midnight (when the budget
            resets). Use this as the value of the ``Retry-After`` HTTP response header.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Daily budget exceeded; resets in {retry_after_seconds}s"
        )


# ---------------------------------------------------------------------------
# SQLModel table
# ---------------------------------------------------------------------------


class UserBudget(SQLModel, table=True):
    """One row per user_id; reset nightly at midnight UTC.

    Fields:
        user_id:           Primary key — the JWT sub (email address).
        usage_date:        The UTC date this row's counts apply to.
        request_count:     Number of /chat or /chat/stream calls today.
        input_token_count: Cumulative OpenAI input tokens today.
    """

    # Use __tablename__ to avoid collision with any future rename
    __tablename__ = "userbudget"  # type: ignore[assignment]

    user_id: str = Field(primary_key=True)
    # Stored as ISO date string (YYYY-MM-DD) — SQLite has no native date type
    usage_date: str = Field(default="")
    request_count: int = Field(default=0)
    input_token_count: int = Field(default=0)


# Create the table in the shared DB at import time (mirrors session_store pattern).
# The engine is already initialised by session_store; this call is idempotent.
SQLModel.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _seconds_to_next_midnight(now: datetime) -> int:
    """Return the number of seconds from `now` (UTC) to the next UTC midnight."""
    from datetime import timedelta

    tomorrow = (now.date() + timedelta(days=1))
    next_midnight = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, tzinfo=timezone.utc
    )
    delta = next_midnight - now
    return max(1, int(delta.total_seconds()))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_and_increment(user_id: str, input_tokens: int = 0) -> None:
    """Gate a chat request against the per-user daily budget.

    Resets the budget row when ``usage_date`` is stale (not today UTC).
    Checks both caps BEFORE incrementing so the budget is precise.
    Raises ``BudgetExceeded`` carrying ``retry_after_seconds`` when exceeded.

    Args:
        user_id:      The authenticated user's ID (JWT sub).  Must come from
                      the JWT, never from the request body (T-02-05-03).
        input_tokens: OpenAI input token count for this request (optional;
                      pass 0 when unknown — only request_count will be tracked).

    Raises:
        BudgetExceeded: When either the request or input-token daily cap is hit.
    """
    now = _now()
    today_str = now.date().isoformat()  # e.g. "2026-06-09"

    with Session(engine) as db:
        row: Optional[UserBudget] = db.get(UserBudget, user_id)

        if row is None:
            # First request ever for this user
            row = UserBudget(
                user_id=user_id,
                usage_date=today_str,
                request_count=0,
                input_token_count=0,
            )
            db.add(row)
        elif row.usage_date != today_str:
            # New day — reset counts
            row.usage_date = today_str
            row.request_count = 0
            row.input_token_count = 0

        # Check caps BEFORE incrementing
        new_request_count = row.request_count + 1
        new_token_count = row.input_token_count + input_tokens

        if new_request_count > settings.daily_request_budget:
            db.commit()  # persist any reset that happened above
            raise BudgetExceeded(_seconds_to_next_midnight(now))

        if new_token_count > settings.daily_input_token_budget:
            db.commit()
            raise BudgetExceeded(_seconds_to_next_midnight(now))

        # Increment and persist
        row.request_count = new_request_count
        row.input_token_count = new_token_count
        db.add(row)
        db.commit()


def current_usage(user_id: Optional[str] = None) -> list[dict] | dict:
    """Return per-user daily usage for the /admin/budgets endpoint.

    Args:
        user_id: When provided, return a single dict for that user.
                 When None, return a list of dicts for all users.

    Returns:
        A dict with keys ``user_id``, ``usage_date``, ``request_count``,
        ``input_token_count`` when ``user_id`` is specified; a list of such
        dicts when ``user_id`` is None.  Returns an empty dict for an unknown
        user_id (no row exists yet).
    """
    with Session(engine) as db:
        if user_id is not None:
            row = db.get(UserBudget, user_id)
            if row is None:
                return {"user_id": user_id, "usage_date": "", "request_count": 0, "input_token_count": 0}
            return {
                "user_id": row.user_id,
                "usage_date": row.usage_date,
                "request_count": row.request_count,
                "input_token_count": row.input_token_count,
            }

        rows = list(db.exec(select(UserBudget)).all())
        return [
            {
                "user_id": r.user_id,
                "usage_date": r.usage_date,
                "request_count": r.request_count,
                "input_token_count": r.input_token_count,
            }
            for r in rows
        ]
