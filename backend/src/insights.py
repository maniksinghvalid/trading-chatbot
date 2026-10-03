"""
insights.py — grounded visual data for chat answers.

Spec: docs/superpowers/specs/2026-10-03-report-insights-visuals-design.md

Every value comes from Pinecone record metadata or from tables parsed out of the
stored report text, or is computed from those here. Nothing is read from LLM
output. Parsers return None when a table is missing or malformed, so a visual is
dropped rather than guessed.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import src.pinecone_client as pc

logger = logging.getLogger(__name__)

_LABEL_MAX = 48

# Producer chunking (ai-trading-claude/scripts/trade_memory.py::_chunk_by_section):
# sections longer than 1500 chars become 1500-char windows overlapping by 100.
_WINDOW = 1500
_OVERLAP = 100


def report_text(chunks: list[dict]) -> str:
    """Re-assemble a report from its chunks (in chunk order), undoing the producer's
    windowing: a full-length window followed by the same section continues it."""
    sections: list[str] = []
    prev_slug, prev_len = None, 0
    for chunk in chunks:
        text = chunk.get("text") or ""
        slug = (chunk.get("metadata") or {}).get("section")
        if sections and slug == prev_slug and prev_len == _WINDOW:
            sections[-1] += text[_OVERLAP:]
        else:
            sections.append(text)
        prev_slug, prev_len = slug, len(text)
    return "\n".join(sections)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every markdown table in `text` as (lower-cased header cells, body rows)."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2 and set(block[1].replace("|", "").strip()) <= set("-: "):
            tables.append(([h.lower() for h in _cells(block[0])], [_cells(r) for r in block[2:]]))
        block = []
    return tables


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(cell: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(cell)]


def _num(cell: str) -> Optional[float]:
    """The single number in a cell ('$10.00', '~$1.55', '+/- 20.9%', '+$0.31'), unsigned.
    None when the cell holds no number or several (ranges like '$5.50–$6.00')."""
    nums = _numbers(cell)
    return nums[0] if len(nums) == 1 else None


def _range(cell: str) -> Optional[tuple[float, float]]:
    nums = _numbers(cell)
    if len(nums) == 2 and nums[0] < nums[1]:
        return nums[0], nums[1]
    return None


def _label(cell: str) -> str:
    return cell.replace("**", "").strip()[:_LABEL_MAX]


def _col(header: list[str], *names: str) -> Optional[int]:
    """Index of the first header cell starting with any of `names`."""
    return next((i for i, h in enumerate(header) if h.startswith(names)), None)


_CURRENT_PRICE = re.compile(r"\*\*Current Price:\*\*\s*(?:[A-Z]{3}\s*)?~?\$?(\d[\d,]*(?:\.\d+)?)")


def parse_current_price(text: str) -> Optional[float]:
    """Price stated in the report itself (legacy metadata can disagree with it)."""
    m = _CURRENT_PRICE.search(text)
    return float(m.group(1).replace(",", "")) if m else None


def parse_expected_move(text: str, price: float) -> Optional[dict]:
    for header, rows in _tables(text):
        i_tf, i_rng = _col(header, "timeframe"), _col(header, "range")
        if i_tf is None or i_rng is None:
            continue
        i_pct = next((i for i, h in enumerate(header) if "%" in h), None)
        ranges = []
        for row in rows:
            if len(row) != len(header):
                continue
            low_high = _range(row[i_rng])
            if not low_high:
                continue
            ranges.append({
                "label": _label(row[i_tf]),
                "low": low_high[0],
                "high": low_high[1],
                "pct": _num(row[i_pct]) if i_pct is not None else None,
                "approx": "~" in row[i_rng],
            })
        if ranges:
            return {"price": price, "ranges": ranges[:4]}
    return None


def parse_key_levels(text: str, price: float) -> Optional[dict]:
    for header, rows in _tables(text):
        i_level, i_price = _col(header, "level"), _col(header, "price")
        if i_level is None or i_price is None:
            continue
        i_note = _col(header, "significance")
        levels = []
        for row in rows:
            if len(row) != len(header) or row[i_level].lower().startswith("current price"):
                continue
            value = _num(row[i_price])
            if value is None or not (0.1 * price <= value <= 10 * price):
                continue
            levels.append({
                "label": _label(row[i_level]),
                "price": value,
                "note": _label(row[i_note]) if i_note is not None else None,
                "approx": "~" in row[i_price],
            })
        if levels:
            levels.sort(key=lambda lv: lv["price"], reverse=True)
            return {"price": price, "levels": levels[:12]}
    return None


def payoff(legs: list[dict], price: float, includes_stock: bool) -> dict:
    """Per-share P/L at expiration (spec §5). Piecewise linear, kinks at the strikes."""
    strikes = sorted({leg["strike"] for leg in legs})

    def pl(s: float) -> float:
        value = (s - price) if includes_stock else 0.0
        for leg in legs:
            k = leg["strike"]
            intrinsic = max(s - k, 0.0) if leg["type"] == "call" else max(k - s, 0.0)
            value += (intrinsic - leg["premium"]) * (1 if leg["action"] == "buy" else -1)
        return value

    lo, hi = 0.6 * min(strikes + [price]), 1.4 * max(strikes + [price])
    xs = sorted({round(lo + (hi - lo) * i / 59, 2) for i in range(60)} | set(strikes))
    kinks = [0.0] + strikes + [hi]
    values = [pl(s) for s in kinks]
    slope = pl(strikes[-1] + 1) - pl(strikes[-1])  # constant above the highest strike
    breakevens: list[float] = []
    # ponytail: a breakeven landing exactly on a strike isn't reported (strict sign change).
    for (a, fa), (b, fb) in zip(zip(kinks, values), zip(kinks[1:], values[1:])):
        if fa * fb < 0:
            breakevens.append(round(a - fa * (b - a) / (fb - fa), 2))
    return {
        "curve": [[x, round(pl(x), 2)] for x in xs],
        "breakevens": breakevens,
        "max_gain": None if slope > 1e-9 else round(max(values), 2),
        "max_loss": None if slope < -1e-9 else round(min(values), 2),
    }


_STRATEGY_1 = re.compile(r"^###\s*Strategy 1:\s*(.+)$", re.M)
_NEXT_HEADING = re.compile(r"^#{2,3}\s", re.M)
_STOCK_STRATEGY = re.compile(r"collar|covered call|protective put", re.I)


def parse_strategy(text: str, price: float) -> Optional[dict]:
    """Strategy 1 of the report's Recommended Strategies, with its payoff. None when
    its legs don't parse or span several expirations (e.g. PMCC)."""
    m = _STRATEGY_1.search(text)
    if not m:
        return None
    name = _label(re.split(r"\s+[—–-]\s+", m.group(1))[0])
    body = text[m.end():]
    nxt = _NEXT_HEADING.search(body)
    body = body[: nxt.start()] if nxt else body

    for header, rows in _tables(body):
        i_act, i_strike, i_type = _col(header, "action"), _col(header, "strike"), _col(header, "type")
        i_exp = _col(header, "expir")
        i_px = next((i for i, h in enumerate(header)
                     if i != i_strike and ("price" in h or h.startswith("premium"))), None)
        if None in (i_act, i_strike, i_type, i_exp, i_px):
            continue
        legs: list[dict] = []
        expirations: set[str] = set()
        for row in rows:
            if len(row) != len(header):
                continue
            action, kind = row[i_act].lower(), row[i_type].lower()
            if "call" not in kind and "put" not in kind:
                continue  # summary / stock rows aren't legs
            strike, premium = _num(row[i_strike]), _num(row[i_px])
            if action not in ("buy", "sell") or kind not in ("call", "put") or strike is None or premium is None:
                return None  # spec §5: one unparseable leg voids the payoff, never a partial position
            legs.append({"action": action, "type": kind, "strike": strike,
                         "premium": premium, "approx": "~" in row[i_px]})
            expirations.add(row[i_exp])
        break  # only the first legs table belongs to Strategy 1
    else:
        return None

    if not legs or len(legs) > 4 or len(expirations) != 1:
        return None
    includes_stock = bool(_STOCK_STRATEGY.search(name)) and "poor man" not in name.lower()
    return {
        "name": name,
        "expiration": _label(expirations.pop()),
        "includes_stock": includes_stock,
        "price": price,
        "legs": legs,
        **payoff(legs, price, includes_stock),
    }


# Mirrors the scoring contract (README / trade/SKILL.md): 25/25/20/15/15.
_DIMENSIONS = (
    ("Technical", "technical_score", 0.25),
    ("Fundamental", "fundamental_score", 0.25),
    ("Sentiment", "sentiment_score", 0.20),
    ("Risk", "risk_score", 0.15),
    ("Thesis", "thesis_score", 0.15),
)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _source(meta: dict) -> dict:
    return {"source_path": meta.get("source_path", ""), "generated_date": meta.get("generated_date", "")}


def score_card(meta: dict) -> Optional[dict]:
    if not _is_num(meta.get("composite_score")):
        return None
    return {
        "composite": meta["composite_score"],
        "grade": meta.get("grade"),
        "signal": meta.get("signal"),
        "dimensions": [
            {"name": name, "score": meta[key], "weight": weight}
            for name, key, weight in _DIMENSIONS
            if _is_num(meta.get(key))
        ],
        "price": meta["price_at_analysis"] if _is_num(meta.get("price_at_analysis")) else None,
        "stop_loss": meta["stop_loss"] if _is_num(meta.get("stop_loss")) else None,
        "catalyst_date": meta.get("nearest_catalyst_date") or None,
        "source": _source(meta),
    }


def trend(analysis_runs: list[dict], options_runs: list[dict], focus: bool) -> Optional[dict]:
    """One point per date (runs arrive oldest → newest, so the day's latest wins);
    ANALYSIS price/signal override OPTIONS on shared dates."""
    points: dict[str, dict] = {}
    for m in options_runs:
        d = m.get("generated_date")
        if not d:
            continue
        p = points.setdefault(d, {"date": d})
        if _is_num(m.get("price_at_analysis")):
            p["price"] = m["price_at_analysis"]
        if _is_num(m.get("iv_rank")):
            p["iv_rank"] = m["iv_rank"]
        if m.get("signal"):
            p["signal"] = m["signal"]
    for m in analysis_runs:
        d = m.get("generated_date")
        if not d:
            continue
        p = points.setdefault(d, {"date": d})
        if _is_num(m.get("price_at_analysis")):
            p["price"] = m["price_at_analysis"]
        if _is_num(m.get("composite_score")):
            p["score"] = m["composite_score"]
        if m.get("signal"):
            p["signal"] = m["signal"]
    series = [points[d] for d in sorted(points)][-60:]
    return {"points": series, "focus": focus} if len(series) >= 2 else None


def build_insights(ticker: Optional[str], context_types: set, intent: str) -> Optional[dict]:
    """Grounded visual payload for an answer about `ticker` (spec §4.3). Never raises:
    each section is built in isolation and dropped (with a warning) on failure."""
    if not ticker:
        return None
    trajectory = intent == "trajectory"
    if not (trajectory or {"ANALYSIS", "OPTIONS"} & set(context_types)):
        return None
    out: dict[str, Any] = {}

    def safe(name: str, build) -> Any:
        try:
            return build()
        except Exception as exc:
            logger.warning("insights: %s failed for %s: %s", name, ticker, exc)
            return None

    def section(name: str, build) -> None:
        value = safe(name, build)
        if value:
            out[name] = value

    def sourced(value: Optional[dict], src: dict) -> Optional[dict]:
        return {**value, "source": src} if value else None

    runs = {
        rt: safe(f"{rt} runs", lambda rt=rt: pc.run_metadata(ticker, rt)) or []
        for rt in ("ANALYSIS", "OPTIONS")
    }

    if "ANALYSIS" in context_types and runs["ANALYSIS"]:
        section("score", lambda: score_card(runs["ANALYSIS"][-1]))

    if "OPTIONS" in context_types:
        chunks = safe("options report", lambda: pc.latest_run_chunks(ticker, "OPTIONS")) or []
        if chunks:
            text = report_text(chunks)
            meta = chunks[0].get("metadata") or {}
            src = _source(meta)
            price = parse_current_price(text)
            if price is None and _is_num(meta.get("price_at_analysis")):
                price = float(meta["price_at_analysis"])
            if _is_num(meta.get("iv_rank")):
                out["iv"] = {"iv_rank": meta["iv_rank"], "source": src}
            if price:
                section("expected_move", lambda: sourced(parse_expected_move(text, price), src))
                section("key_levels", lambda: sourced(parse_key_levels(text, price), src))
                section("strategy", lambda: sourced(parse_strategy(text, price), src))

    if out or trajectory:
        section("trend", lambda: trend(runs["ANALYSIS"], runs["OPTIONS"], focus=trajectory))
    return {"ticker": ticker, **out} if out else None
