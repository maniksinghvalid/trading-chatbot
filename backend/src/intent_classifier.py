"""
intent_classifier.py — Intent classification via a fixed-schema OpenAI call.

Public API:
  Intent: Literal["factual", "trajectory", "comparison", "action", "chitchat"]
      The five supported intent labels.

  classify_intent(text: str) -> dict
      Calls the LLM with a fixed JSON-schema instruction and returns a dict:
        {
          "intent": one of the five Intent labels,
          "tickers": list[str] of uppercase symbols mentioned.
        }
      On JSON decode failure or an out-of-enum intent the function DEGRADES
      GRACEFULLY to {"intent": "factual", "tickers": extract_tickers(text)}.
      Never raises for bad LLM output.

Intent labels:
  factual     — current state / price / status ("what is AAPL trading at?")
  trajectory  — historical or trend query ("how has NVDA done this year?")
  comparison  — multi-ticker comparison ("compare NVDA and AMD")
  action      — buy/sell/hold recommendation ("should I buy TSLA?")
  chitchat    — off-topic / greeting / small-talk ("hi there")

Threat mitigations:
  T-02-01-03 — degrades to factual on malformed input; no stack-trace leak.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

# Re-export complete in this module's namespace so tests can monkeypatch it.
from src.llm_client import complete  # noqa: F401
from src.ticker_extractor import extract_tickers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent type
# ---------------------------------------------------------------------------

Intent = Literal["factual", "trajectory", "comparison", "action", "chitchat"]

_VALID_INTENTS: frozenset[str] = frozenset(
    {"factual", "trajectory", "comparison", "action", "chitchat"}
)

# ---------------------------------------------------------------------------
# LLM instruction (fixed schema)
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are an intent classifier for a stock-market research chatbot. "
    "Given a user message, classify it into exactly one of these intent labels:\n"
    "  factual     — asks about current price, status, or data (e.g. 'what is AAPL trading at?')\n"
    "  trajectory  — asks about historical performance or trend (e.g. 'how has NVDA done this year?')\n"
    "  comparison  — compares two or more tickers (e.g. 'compare NVDA and AMD')\n"
    "  action      — asks for buy/sell/hold recommendation (e.g. 'should I buy TSLA?')\n"
    "  chitchat    — off-topic, greeting, or small-talk (e.g. 'hi there')\n\n"
    "Also extract any stock ticker symbols explicitly or implicitly mentioned.\n\n"
    "Respond with ONLY a JSON object in this exact format (no markdown, no commentary):\n"
    '{"intent": "<label>", "tickers": ["SYM1", "SYM2"]}\n\n'
    "If no tickers are mentioned, use an empty array: []"
)

# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def classify_intent(text: str) -> dict[str, Any]:
    """Classify the intent of *text* and extract mentioned tickers.

    Makes a single LLM call with a fixed-schema instruction prompt. On any
    parse failure or out-of-enum intent, degrades gracefully to the 'factual'
    intent and falls back to regex ticker extraction.

    Args:
        text: Natural-language user message.

    Returns:
        dict with keys:
          intent (str): one of factual|trajectory|comparison|action|chitchat.
          tickers (list[str]): uppercase stock symbols mentioned.
    """
    try:
        response = complete(
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:
        logger.error("classify_intent: LLM call failed: %s", exc)
        return _fallback(text)

    return _parse_response(response, text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_response(response: str, original_text: str) -> dict[str, Any]:
    """Parse the LLM JSON response; return fallback dict on any error."""
    try:
        parsed = json.loads(response.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "classify_intent: JSON decode failed (%s) for response %r — degrading to factual",
            exc,
            response[:120],
        )
        return _fallback(original_text)

    intent = parsed.get("intent")
    if intent not in _VALID_INTENTS:
        logger.warning(
            "classify_intent: out-of-enum intent %r — degrading to factual",
            intent,
        )
        return _fallback(original_text)

    # Normalise tickers: uppercase, deduplicate, preserve order
    raw_tickers = parsed.get("tickers") or []
    if not isinstance(raw_tickers, list):
        raw_tickers = []
    tickers: list[str] = []
    seen: set[str] = set()
    for sym in raw_tickers:
        sym = str(sym).strip().upper()
        if sym and sym not in seen:
            tickers.append(sym)
            seen.add(sym)

    return {"intent": str(intent), "tickers": tickers}


def _fallback(text: str) -> dict[str, Any]:
    """Return a safe fallback dict: intent='factual', tickers from regex."""
    tickers = extract_tickers(text) if text and text.strip() else []
    return {"intent": "factual", "tickers": tickers}
