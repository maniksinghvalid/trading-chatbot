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
from typing import Optional

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
