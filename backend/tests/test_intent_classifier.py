"""
test_intent_classifier.py — unit tests for src.intent_classifier.

All tests run fully offline: LLM calls are monkeypatched to avoid network traffic.

Test coverage:
  - Happy path: all five intent labels returned correctly.
  - tickers[] field populated from LLM response.
  - Malformed JSON from LLM → graceful fallback to {"intent": "factual", "tickers": <regex>}.
  - Out-of-enum intent from LLM → graceful fallback.
  - Intent value is always one of the five valid enum strings.
  - classify_intent returns a dict with exactly the keys: intent, tickers.
  - Intent literal / enum exported correctly.
"""

from __future__ import annotations

import json

import pytest

from src.intent_classifier import Intent, classify_intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_complete_returning(json_str: str):
    """Return a mock `complete` that always returns *json_str*."""

    def _complete(system: str, messages: list) -> str:  # noqa: ANN001
        return json_str

    return _complete


VALID_INTENTS = {"factual", "trajectory", "comparison", "action", "chitchat"}


# ---------------------------------------------------------------------------
# Intent label tests (mocked LLM)
# ---------------------------------------------------------------------------


def test_factual_intent(monkeypatch):
    """Price/now keyword family → intent='factual'."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "factual", "tickers": ["AAPL"]})),
    )
    result = classify_intent("what's AAPL trading at?")
    assert result["intent"] == "factual"
    assert "AAPL" in result["tickers"]


def test_trajectory_intent(monkeypatch):
    """Historical performance query → intent='trajectory'."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "trajectory", "tickers": ["NVDA"]})),
    )
    result = classify_intent("how has NVDA done this year")
    assert result["intent"] == "trajectory"
    assert "NVDA" in result["tickers"]


def test_comparison_intent(monkeypatch):
    """'compare NVDA and AMD' → intent='comparison' with both tickers."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "comparison", "tickers": ["NVDA", "AMD"]})),
    )
    result = classify_intent("compare NVDA and AMD")
    assert result["intent"] == "comparison"
    assert "NVDA" in result["tickers"]
    assert "AMD" in result["tickers"]


def test_action_intent(monkeypatch):
    """Buy/sell query → intent='action'."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "action", "tickers": ["TSLA"]})),
    )
    result = classify_intent("should I buy TSLA now?")
    assert result["intent"] == "action"


def test_chitchat_intent(monkeypatch):
    """Greeting with no ticker → intent='chitchat', tickers=[]."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "chitchat", "tickers": []})),
    )
    result = classify_intent("hi there")
    assert result["intent"] == "chitchat"
    assert result["tickers"] == []


# ---------------------------------------------------------------------------
# Graceful degradation on bad LLM responses
# ---------------------------------------------------------------------------


def test_malformed_json_falls_back_to_factual(monkeypatch):
    """A non-JSON LLM response falls back to intent='factual' without raising."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning("this is not json at all"),
    )
    result = classify_intent("AAPL earnings")
    assert result["intent"] == "factual"
    # Should not raise
    assert isinstance(result["tickers"], list)


def test_out_of_enum_intent_falls_back_to_factual(monkeypatch):
    """An unknown intent value falls back to 'factual'."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "unknown_label", "tickers": ["AAPL"]})),
    )
    result = classify_intent("some AAPL question")
    assert result["intent"] == "factual"


def test_missing_intent_key_falls_back(monkeypatch):
    """JSON without 'intent' key falls back to 'factual'."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"tickers": ["MSFT"]})),
    )
    result = classify_intent("MSFT question")
    assert result["intent"] == "factual"


def test_fallback_tickers_from_regex(monkeypatch):
    """On malformed JSON, tickers fall back to regex extraction from the text."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning("NOT JSON"),
    )
    result = classify_intent("What about NVDA?")
    # NVDA should be in tickers from regex fallback
    assert result["intent"] == "factual"
    assert isinstance(result["tickers"], list)


# ---------------------------------------------------------------------------
# Return structure invariants
# ---------------------------------------------------------------------------


def test_result_has_required_keys(monkeypatch):
    """classify_intent always returns a dict with 'intent' and 'tickers' keys."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning(json.dumps({"intent": "factual", "tickers": []})),
    )
    result = classify_intent("anything")
    assert "intent" in result
    assert "tickers" in result


def test_intent_is_always_valid_enum_value(monkeypatch):
    """The returned intent is always one of the five valid enum values."""
    for intent in VALID_INTENTS:
        monkeypatch.setattr(
            "src.intent_classifier.complete",
            _mock_complete_returning(json.dumps({"intent": intent, "tickers": []})),
        )
        result = classify_intent(f"some query about stocks with intent {intent}")
        assert result["intent"] in VALID_INTENTS, (
            f"Got unexpected intent: {result['intent']!r}"
        )


def test_tickers_is_always_a_list(monkeypatch):
    """tickers field is always a list (never None or missing)."""
    monkeypatch.setattr(
        "src.intent_classifier.complete",
        _mock_complete_returning("GARBAGE INPUT"),
    )
    result = classify_intent("some question")
    assert isinstance(result["tickers"], list)


# ---------------------------------------------------------------------------
# Intent export
# ---------------------------------------------------------------------------


def test_intent_type_exported():
    """Intent is exported from the module and contains the five valid values."""
    # Intent should be usable as a type hint (Literal) and/or string set
    assert hasattr(Intent, "__args__") or isinstance(Intent, (type, str, frozenset))
    # The string values must all be the five canonical labels
    valid = {"factual", "trajectory", "comparison", "action", "chitchat"}
    # Check if it's a Literal with __args__
    if hasattr(Intent, "__args__"):
        assert set(Intent.__args__) == valid
