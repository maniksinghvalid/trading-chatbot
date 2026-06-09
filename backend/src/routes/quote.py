"""
routes/quote.py — GET /quote/{ticker} live market-data endpoint (slice 7, QUOTE-01).

Returns a live quote dict from market_data.quote():
  {price, day_change_pct, volume, timestamp, source}

Error handling (T-02-02-01):
  QuoteUnavailableError → HTTP 503 with a generic "quote provider unavailable"
  detail.  No stack trace or key material in the response body.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.market_data import QuoteUnavailableError
import src.market_data as market_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quote", tags=["quote"])


@router.get("/{ticker}")
def get_quote(ticker: str) -> dict:
    """Return a live market-data quote for *ticker*.

    Args:
        ticker: Stock symbol as a path parameter (e.g. "AAPL").  The handler
                uppercases it before passing to market_data.quote().

    Returns:
        200 dict: {price, day_change_pct, volume, timestamp, source}.

    Raises:
        HTTPException 503: when market_data.quote() raises QuoteUnavailableError.
                           Detail is a generic message — no stack trace or key
                           material is included (T-02-02-01).
    """
    try:
        return market_data.quote(ticker.upper())
    except QuoteUnavailableError as exc:
        logger.error("get_quote: provider unavailable for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=503,
            detail="quote provider unavailable",
        ) from exc
