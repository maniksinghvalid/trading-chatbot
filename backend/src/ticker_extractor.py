"""
ticker_extractor.py — Rule-based + LLM-fallback ticker resolution.

Public API:
  KNOWN_TICKERS: set[str]
      Static allowlist of known ticker symbols (large-caps + common names).
      Guards false positives such as "I" (Intelsat) or "A" that appear as
      uppercase tokens in natural-language text but are not valid tickers.

  extract_tickers(text: str) -> list[str]
      First pass: regex `$?([A-Z]{1,5}(\\.[A-Z])?)` captures potential
      uppercase symbols; single-char matches are accepted ONLY if they are in
      KNOWN_TICKERS (Intelsat false-positive guard).  De-duplicates, preserving
      order.  If the regex pass yields an empty list, falls back to the LLM to
      resolve company names ("Apple" → "AAPL").

Threat mitigations:
  T-02-01-01 — 1-char candidates validated against KNOWN_TICKERS.
  T-02-01-02 — LLM fallback fires only when regex yields zero tickers.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Re-export complete so tests can monkeypatch this module's reference.
from src.llm_client import complete  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known-tickers allowlist
# ---------------------------------------------------------------------------
# Seeded from common large-cap symbols.  Extend this list as holdings grow.
# Single-character candidates from the regex pass are accepted ONLY when they
# appear in this set (e.g. "V" for Visa is OK; "I" for Intelsat is NOT by
# default — add "I" here if you need it).

KNOWN_TICKERS: set[str] = {
    # Mega-cap / commonly held
    "AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "GOOG", "AMZN", "TSLA", "META",
    # Berkshire (dotted form handled by regex but listed here for clarity)
    "BRK.B", "BRK.A",
    # Financials / ETFs
    "JPM", "BAC", "GS", "V", "MA",
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF",
    # Other large-caps
    "NFLX", "PYPL", "UBER", "LYFT", "SHOP", "SQ", "COIN", "HOOD",
    "INTC", "QCOM", "TXN", "AVGO", "MU", "AMAT", "LRCX",
    "DIS", "NKLA", "F", "GM", "FORD",
    "WMT", "TGT", "COST", "HD", "LOW",
    "JNJ", "PFE", "MRNA", "ABBV", "LLY", "BMY",
    "XOM", "CVX", "COP", "SLB",
    "GE", "CAT", "MMM", "HON", "BA",
    "TWTR", "SNAP", "PINS",
    # Common 2-letter symbols (less risky than 1-letter)
    "NU", "NIO", "PL",
}

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------
# Matches:  optional $, 1-5 uppercase letters, optional ".<uppercase letter>"
# Examples matched: AAPL, $MSFT, BRK.B
_TICKER_RE = re.compile(r"\$?([A-Z]{1,5}(?:\.[A-Z])?)\b")

# ---------------------------------------------------------------------------
# LLM prompt (fixed schema)
# ---------------------------------------------------------------------------
_LLM_SYSTEM = (
    "You are a financial ticker resolver. Given a message, extract any mentioned "
    "company names or informal references to publicly traded companies and return "
    "the corresponding uppercase US stock ticker symbols. "
    "Return ONLY a comma-separated list of symbols (e.g. AAPL,MSFT). "
    "If no companies are mentioned, return an empty string. "
    "Do NOT include explanations, punctuation, or any other text."
)


def extract_tickers(text: str) -> list[str]:
    """Extract ticker symbols from *text*, returning a deduplicated ordered list.

    Algorithm:
      1. Regex first pass: find all uppercase token candidates.
      2. Filter: single-char candidates accepted only if in KNOWN_TICKERS.
         Multi-char (2–5 chars) candidates accepted unconditionally.
      3. If the first pass yields an empty list, call the LLM to resolve
         company names / informal mentions.
      4. Parse the LLM response as a comma-separated symbol list; validate and
         include each symbol (accept even if not in KNOWN_TICKERS — the LLM
         is the resolver of last resort for novel tickers).
      5. Return deduplicated, ordered list.

    Args:
        text: Natural-language user message (e.g. "how is apple doing").

    Returns:
        List of uppercase ticker strings (may be empty if nothing resolves).
    """
    if not text or not text.strip():
        return []

    # --- Pass 1: regex ---
    candidates: list[str] = []
    seen: set[str] = set()
    for match in _TICKER_RE.finditer(text):
        symbol = match.group(1).upper()
        # False-positive guard: single-char candidates require explicit listing
        if len(symbol.replace(".", "")) == 1 and symbol not in KNOWN_TICKERS:
            logger.debug("extract_tickers: dropping 1-char candidate %r (not in KNOWN_TICKERS)", symbol)
            continue
        if symbol not in seen:
            candidates.append(symbol)
            seen.add(symbol)

    if candidates:
        return candidates

    # --- Pass 2: LLM fallback ---
    logger.debug("extract_tickers: no regex match for %r — invoking LLM fallback", text[:80])
    try:
        response = complete(
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:
        logger.error("extract_tickers: LLM fallback failed: %s", exc)
        return []

    # Parse comma-separated list; strip whitespace and empty parts
    if not response or not response.strip():
        return []

    llm_tickers: list[str] = []
    llm_seen: set[str] = set()
    for part in response.split(","):
        sym = part.strip().upper()
        if not sym:
            continue
        # Accept any non-empty symbol from the LLM (trust the resolver for novel tickers)
        if sym not in llm_seen:
            llm_tickers.append(sym)
            llm_seen.add(sym)

    return llm_tickers
