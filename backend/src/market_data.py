"""
market_data.py — Live market-data quote layer (slice 7, QUOTE-01).

Public API:
  QuoteUnavailableError(RuntimeError)
      Raised when the provider has no data or the fetch fails.  Callers catch
      this and return a clean 503 / graceful no-quote path — no stack/key leak.

  quote(ticker: str) -> dict
      Returns a live quote dict:
        {
          "price": float,
          "day_change_pct": float,
          "volume": int,
          "timestamp": str,   # ISO-8601 UTC timestamp of fetch time
          "source": "yfinance",
        }
      Quotes are cached in memory for _CACHE_TTL_SECONDS (900s ≈ 15 min).
      The ticker is normalised to uppercase before cache lookup.

  _fetch_raw(ticker: str) -> dict
      Internal helper; factored out so tests can monkeypatch it.  Returns
      {"price", "day_change_pct", "volume"} or raises RuntimeError on failure.

Threat mitigations applied:
  T-02-02-01 — Provider errors wrapped in QuoteUnavailableError; no stack/key leak.
  T-02-02-02 — 15-min TTL cache; quote fetched only on intent-gated requests.
  T-02-02-03 — Every quote carries a UTC timestamp and source label.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

#: TTL for in-memory quote cache (~15 minutes, per slice-7 spec).
_CACHE_TTL_SECONDS: int = 900

#: Internal cache: {TICKER: {"data": dict, "fetched_at": monotonic_time}}
_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------


class QuoteUnavailableError(RuntimeError):
    """Raised when the market-data provider cannot supply a quote.

    Route handlers catch this and return HTTP 503 with a generic body so
    that no API details, stack traces, or key material leaks to the caller
    (T-02-02-01).
    """


# ---------------------------------------------------------------------------
# Internal fetch helper (monkeypatch target in tests)
# ---------------------------------------------------------------------------


def _fetch_raw(ticker: str) -> dict[str, Any]:
    """Fetch a raw quote from yfinance for *ticker* (uppercase expected).

    Returns:
        dict with keys "price" (float), "day_change_pct" (float),
        "volume" (int).

    Raises:
        RuntimeError: on any yfinance error or missing data.
    """
    import yfinance as yf  # lazy import — not loaded until first fetch

    info = yf.Ticker(ticker).fast_info

    # fast_info exposes last_price, open, volume, etc.
    price = getattr(info, "last_price", None)
    if price is None or price == 0:
        # Fallback to regularMarketPrice via info dict
        full = yf.Ticker(ticker).info
        price = full.get("regularMarketPrice") or full.get("currentPrice")
        if not price:
            raise RuntimeError(f"No price data available for {ticker!r}")

    # Day change percent
    prev_close = getattr(info, "previous_close", None)
    if prev_close and prev_close != 0:
        day_change_pct = (price - prev_close) / prev_close * 100.0
    else:
        # Try via full info dict
        full_info = yf.Ticker(ticker).info
        day_change_pct = full_info.get("regularMarketChangePercent", 0.0) or 0.0

    volume = getattr(info, "three_month_average_volume", None)
    if volume is None:
        volume = getattr(info, "regular_market_volume", 0) or 0

    return {
        "price": float(price),
        "day_change_pct": float(day_change_pct),
        "volume": int(volume),
    }


# ---------------------------------------------------------------------------
# Public quote function
# ---------------------------------------------------------------------------


def quote(ticker: str) -> dict[str, Any]:
    """Return a live market-data quote for *ticker*, using the in-memory cache.

    The ticker is normalised to uppercase.  On a cache hit (within TTL) the
    cached dict is returned without a network call.  On a cache miss the quote
    is fetched via _fetch_raw and stored in the cache before returning.

    Args:
        ticker: Stock symbol (e.g. "AAPL", "aapl" — case-insensitive).

    Returns:
        dict with keys: price, day_change_pct, volume, timestamp, source.

    Raises:
        QuoteUnavailableError: when the provider has no data or the fetch fails.
    """
    ticker = ticker.upper()
    now = time.monotonic()

    # Cache hit: return cached data if within TTL
    cached = _cache.get(ticker)
    if cached is not None:
        age = now - cached["fetched_at"]
        if age < _CACHE_TTL_SECONDS:
            logger.debug("market_data.quote: cache hit for %s (age=%.1fs)", ticker, age)
            return cached["data"]
        else:
            logger.debug("market_data.quote: cache stale for %s (age=%.1fs)", ticker, age)

    # Cache miss or stale — fetch from provider
    logger.info("market_data.quote: fetching live quote for %s", ticker)
    try:
        raw = _fetch_raw(ticker)
    except Exception as exc:
        logger.error("market_data.quote: provider error for %s: %s", ticker, exc)
        # Do not leak stack trace or internal error details (T-02-02-01)
        raise QuoteUnavailableError("quote provider unavailable") from None

    data: dict[str, Any] = {
        "price": raw["price"],
        "day_change_pct": raw["day_change_pct"],
        "volume": raw["volume"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
    }

    _cache[ticker] = {"data": data, "fetched_at": now}
    return data
