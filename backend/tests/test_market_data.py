"""
test_market_data.py — unit tests for market_data.py (slice 7, QUOTE-01).

All yfinance fetches are mocked via monkeypatching `market_data._fetch_raw`
so tests pass fully offline with no network access.

Coverage:
  - quote() returns five-key dict with source=="yfinance" and ISO timestamp
  - Cache hit: two calls within TTL trigger exactly one _fetch_raw
  - Cache miss after TTL expiry: second call triggers a second _fetch_raw
  - Provider failure raises QuoteUnavailableError (not a bare exception)
  - ticker is uppercased before cache lookup / fetch
  - GET /quote/{ticker} returns 200 + five keys (mocked quote)
  - GET /quote/{ticker} returns 503 when QuoteUnavailableError is raised
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src import market_data
from src.market_data import QuoteUnavailableError, quote
from src.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_RAW = {
    "price": 189.75,
    "day_change_pct": 1.23,
    "volume": 55_000_000,
}

_TICKER = "AAPL"


def _make_fake_fetch(raw: dict | None = None, raise_exc: Exception | None = None):
    """Return a _fetch_raw replacement that returns *raw* or raises *raise_exc*."""
    if raise_exc is not None:
        def _fetch(ticker: str) -> dict:
            raise raise_exc
        return _fetch
    captured = raw or _FAKE_RAW

    def _fetch(ticker: str) -> dict:
        return captured

    return _fetch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the in-memory cache before each test so tests are isolated."""
    market_data._cache.clear()
    yield
    market_data._cache.clear()


@pytest.fixture
def client():
    """FastAPI TestClient for endpoint tests."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# quote() unit tests
# ---------------------------------------------------------------------------


def test_quote_returns_five_key_dict(monkeypatch):
    """quote("AAPL") returns a dict with price, day_change_pct, volume, timestamp, source."""
    monkeypatch.setattr(market_data, "_fetch_raw", _make_fake_fetch())

    result = quote(_TICKER)

    assert isinstance(result, dict), "quote() must return a dict"
    for key in ("price", "day_change_pct", "volume", "timestamp", "source"):
        assert key in result, f"Missing key: {key}"


def test_quote_source_is_yfinance(monkeypatch):
    """source field must be the string 'yfinance'."""
    monkeypatch.setattr(market_data, "_fetch_raw", _make_fake_fetch())

    result = quote(_TICKER)

    assert result["source"] == "yfinance"


def test_quote_timestamp_is_iso8601(monkeypatch):
    """timestamp must be an ISO-8601 string."""
    from datetime import datetime, timezone

    monkeypatch.setattr(market_data, "_fetch_raw", _make_fake_fetch())

    result = quote(_TICKER)
    ts = result["timestamp"]

    assert isinstance(ts, str), "timestamp must be a string"
    # Must parse without error
    parsed = datetime.fromisoformat(ts)
    # Must be UTC-aware or naive (as long as it parses)
    assert parsed is not None


def test_quote_values_match_raw(monkeypatch):
    """Returned price/day_change_pct/volume match the mocked raw data."""
    monkeypatch.setattr(market_data, "_fetch_raw", _make_fake_fetch())

    result = quote(_TICKER)

    assert result["price"] == _FAKE_RAW["price"]
    assert result["day_change_pct"] == _FAKE_RAW["day_change_pct"]
    assert result["volume"] == _FAKE_RAW["volume"]


def test_quote_cache_hit_calls_fetch_once(monkeypatch):
    """Two consecutive calls within TTL trigger exactly one _fetch_raw."""
    call_count = 0

    def _counting_fetch(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        return _FAKE_RAW

    monkeypatch.setattr(market_data, "_fetch_raw", _counting_fetch)

    quote(_TICKER)
    quote(_TICKER)

    assert call_count == 1, (
        f"Expected 1 _fetch_raw call (cache hit on second), got {call_count}"
    )


def test_quote_cache_miss_after_ttl(monkeypatch):
    """After the TTL window expires the cache is bypassed and _fetch_raw called again."""
    call_count = 0

    def _counting_fetch(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        return _FAKE_RAW

    monkeypatch.setattr(market_data, "_fetch_raw", _counting_fetch)

    # First call: populates cache
    quote(_TICKER)

    # Manually expire the cache entry by backdating its timestamp
    import time as _time
    market_data._cache[_TICKER.upper()]["fetched_at"] = (
        _time.monotonic() - market_data._CACHE_TTL_SECONDS - 1
    )

    # Second call: cache is stale — must re-fetch
    quote(_TICKER)

    assert call_count == 2, (
        f"Expected 2 _fetch_raw calls (cache expired), got {call_count}"
    )


def test_quote_uppercase_ticker(monkeypatch):
    """quote() uppercases the ticker for consistent cache keying."""
    call_count = 0

    def _counting_fetch(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        return _FAKE_RAW

    monkeypatch.setattr(market_data, "_fetch_raw", _counting_fetch)

    quote("aapl")
    quote("AAPL")  # should be a cache hit

    assert call_count == 1, (
        "Lower-case 'aapl' and upper-case 'AAPL' must share the same cache entry"
    )


def test_quote_provider_failure_raises_quote_unavailable(monkeypatch):
    """A provider error raises QuoteUnavailableError, not a bare exception."""
    monkeypatch.setattr(
        market_data,
        "_fetch_raw",
        _make_fake_fetch(raise_exc=RuntimeError("yfinance connection error")),
    )

    with pytest.raises(QuoteUnavailableError):
        quote(_TICKER)


def test_quote_provider_failure_no_key_leak(monkeypatch):
    """QuoteUnavailableError message must not contain stack/key material."""
    monkeypatch.setattr(
        market_data,
        "_fetch_raw",
        _make_fake_fetch(raise_exc=ValueError("API_KEY=s3cr3t in traceback")),
    )

    with pytest.raises(QuoteUnavailableError) as exc_info:
        quote(_TICKER)

    # The error message exposed to callers should be generic
    assert "API_KEY" not in str(exc_info.value)
    assert "s3cr3t" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# GET /quote/{ticker} endpoint tests
# ---------------------------------------------------------------------------

_FIXTURE_QUOTE = {
    "price": 189.75,
    "day_change_pct": 1.23,
    "volume": 55_000_000,
    "timestamp": "2026-06-09T14:00:00+00:00",
    "source": "yfinance",
}


def test_quote_endpoint_200(client, monkeypatch):
    """GET /quote/AAPL returns 200 with all five keys when quote() succeeds."""
    monkeypatch.setattr(market_data, "quote", lambda ticker: _FIXTURE_QUOTE)

    resp = client.get("/quote/AAPL")

    assert resp.status_code == 200
    data = resp.json()
    for key in ("price", "day_change_pct", "volume", "timestamp", "source"):
        assert key in data, f"Response missing key: {key}"


def test_quote_endpoint_503_on_unavailable(client, monkeypatch):
    """GET /quote/AAPL returns 503 when quote() raises QuoteUnavailableError."""
    def _failing_quote(ticker: str):
        raise QuoteUnavailableError("provider down")

    monkeypatch.setattr(market_data, "quote", _failing_quote)

    resp = client.get("/quote/AAPL")

    assert resp.status_code == 503
    # Generic detail — no stack trace
    detail = resp.json().get("detail", "")
    assert "unavailable" in detail.lower()


def test_quote_endpoint_no_stack_trace(client, monkeypatch):
    """503 response body must not contain stack trace text."""
    def _failing_quote(ticker: str):
        raise QuoteUnavailableError("provider down")

    monkeypatch.setattr(market_data, "quote", _failing_quote)

    resp = client.get("/quote/AAPL")

    body = resp.text
    assert "Traceback" not in body
    assert "QuoteUnavailableError" not in body
