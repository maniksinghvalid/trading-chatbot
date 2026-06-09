"""
test_ticker_extractor.py — unit tests for src.ticker_extractor.

All tests run fully offline: LLM calls are monkeypatched to avoid network traffic.

Test coverage:
  - Regex fast-path: explicit uppercase ticker symbols resolved without LLM call.
  - Dollar-sign prefix: $AAPL stripped and resolved by regex.
  - Dotted form: BRK.B captured correctly.
  - False-positive guard: single-char "I" not returned unless in KNOWN_TICKERS.
  - LLM fallback: company-name mentions (e.g. "Apple") resolved via mocked LLM.
  - LLM not called when regex already resolves tickers (assert call_count == 0).
  - Empty input: returns [].
  - LLM fallback that returns nothing: returns [].
  - Deduplication: repeated symbols collapse to one entry.
"""

from __future__ import annotations

import pytest

from src.ticker_extractor import KNOWN_TICKERS, extract_tickers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_complete_returning(symbols: str):
    """Return a mock `complete` function that always returns *symbols*."""

    def _complete(system: str, messages: list) -> str:  # noqa: ANN001
        return symbols

    return _complete


# ---------------------------------------------------------------------------
# Regex fast-path (no LLM call expected)
# ---------------------------------------------------------------------------


def test_explicit_tickers_no_llm_call(monkeypatch):
    """$AAPL vs MSFT → regex resolves both; LLM is never called."""
    call_count = {"n": 0}

    def _tracking_complete(system, messages):
        call_count["n"] += 1
        return "AAPL,MSFT"

    monkeypatch.setattr("src.ticker_extractor.complete", _tracking_complete)

    result = extract_tickers("$AAPL vs MSFT")

    assert "AAPL" in result
    assert "MSFT" in result
    assert call_count["n"] == 0, (
        "LLM fallback must NOT be called when regex already resolves tickers"
    )


def test_dollar_prefix_stripped():
    """Leading $ is stripped; AAPL is returned."""
    result = extract_tickers("$AAPL looks bullish today")
    assert "AAPL" in result


def test_dotted_form_brk_b(monkeypatch):
    """BRK.B is captured by the dotted-form regex variant."""
    # BRK.B is a regex match (uppercase + dot + uppercase), no LLM needed
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    # Add BRK.B to known tickers for this test context
    result = extract_tickers("BRK.B earnings this quarter")
    # BRK.B should be in result because it matches the dotted regex
    assert "BRK.B" in result


def test_multiple_explicit_tickers(monkeypatch):
    """Multiple uppercase symbols are all returned."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    result = extract_tickers("Compare NVDA AMD MSFT")
    assert "NVDA" in result
    assert "AMD" in result
    assert "MSFT" in result


def test_deduplication(monkeypatch):
    """Repeated ticker symbol is collapsed to one entry."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    result = extract_tickers("AAPL AAPL AAPL")
    assert result.count("AAPL") == 1


# ---------------------------------------------------------------------------
# False-positive guard
# ---------------------------------------------------------------------------


def test_single_char_i_not_returned(monkeypatch):
    """'I' is not treated as a ticker ('I' = Intelsat false-positive guard)."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning(""),  # LLM returns nothing for this query
    )
    result = extract_tickers("should I buy stocks today")
    assert "I" not in result, f"'I' must be filtered out; got {result}"


def test_single_char_a_not_returned(monkeypatch):
    """Single-char 'A' is not returned unless 'A' is in KNOWN_TICKERS."""
    if "A" in KNOWN_TICKERS:
        pytest.skip("'A' is in KNOWN_TICKERS; guard does not apply")
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning(""),
    )
    result = extract_tickers("A quick question about the market")
    assert "A" not in result


# ---------------------------------------------------------------------------
# LLM fallback (company name → symbol)
# ---------------------------------------------------------------------------


def test_company_name_resolved_via_llm(monkeypatch):
    """'how is apple doing' → AAPL via LLM fallback (no uppercase tokens)."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning("AAPL"),
    )
    result = extract_tickers("how is apple doing")
    assert result == ["AAPL"], f"Expected ['AAPL'], got {result}"


def test_llm_fallback_only_when_no_regex_match(monkeypatch):
    """LLM is called exactly once when regex yields nothing."""
    call_count = {"n": 0}

    def _counting_complete(system, messages):
        call_count["n"] += 1
        return "AAPL"

    monkeypatch.setattr("src.ticker_extractor.complete", _counting_complete)

    # "apple" is lowercase → no regex match → LLM fallback invoked
    result = extract_tickers("how is apple doing")
    assert call_count["n"] == 1
    assert "AAPL" in result


def test_llm_fallback_returns_empty_list_on_no_resolution(monkeypatch):
    """LLM returning empty string → extract_tickers returns []."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning(""),
    )
    result = extract_tickers("what is the weather like")
    assert result == []


def test_llm_result_filtered_by_known_tickers(monkeypatch):
    """LLM symbols are validated and included even if only in LLM response."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning("NVDA"),
    )
    result = extract_tickers("how is nvidia doing")
    assert "NVDA" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty_list(monkeypatch):
    """Empty input string → []."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning(""),
    )
    result = extract_tickers("")
    assert result == []


def test_whitespace_only_returns_empty_list(monkeypatch):
    """Whitespace-only input string → []."""
    monkeypatch.setattr(
        "src.ticker_extractor.complete",
        _mock_complete_returning(""),
    )
    result = extract_tickers("   ")
    assert result == []


def test_known_tickers_set_exported():
    """KNOWN_TICKERS is a non-empty set containing common large-cap symbols."""
    assert isinstance(KNOWN_TICKERS, set)
    for sym in ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META"):
        assert sym in KNOWN_TICKERS, f"Expected {sym} in KNOWN_TICKERS"
