# Report Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show grounded visuals (score gauge, trend lines, expected-move bands, key-levels ladder, IV meter, strategy payoff) inline in chat answers, built only from report data.

**Architecture:** A new pure-Python module `backend/src/insights.py` parses stored report text and Pinecone metadata into an `insights` JSON payload. `/chat/stream` builds it in a thread pool alongside the LLM call and emits it as an additive SSE event. The Next.js frontend attaches it to the assistant message and renders hand-built SVG cards from `frontend/components/insights/`.

**Tech Stack:** FastAPI + sse-starlette, Pinecone SDK, pytest (backend); Next.js 16 / React 18, Tailwind 3, vitest (frontend). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-report-insights-visuals-design.md` (amended alongside this plan: `trend.focus` flag; payoff full-width with key levels + IV paired; chart helpers in `lib/chart.ts` so vitest picks them up; `parse_strategy(text, price)` returns None without a `### Strategy 1:` heading instead of falling back to metadata)

## Global Constraints

- No new dependencies in `backend/pyproject.toml` or `frontend/package.json`.
- Pinecone is read-only from this app; no record-schema changes; `schema_version` handling stays in `_normalize`.
- SSE change is additive only: new optional event `insights`, at most once, anywhere between `citations` and `done`; existing event order unchanged.
- No value in the `insights` payload may be derived from LLM output.
- No `dangerouslySetInnerHTML`, no raw HTML (T-06-01); report labels rendered as JSX text.
- Labels truncated to 48 chars; payload bounds: ≤ 60 trend points, ≤ 12 levels, ≤ 4 legs, ≤ 80 curve points, ≤ 4 expected-move ranges.
- Approximate report values (`~`) keep `approx: true` and render with a `~` prefix.
- Producer chunking (from `ai-trading-claude/scripts/trade_memory.py::_chunk_by_section`): sections split on `\n(?=## )` and right-stripped; sections longer than 1500 chars become 1500-char windows with 100-char overlap.
- Insights must never break chat: no `error` event, never block tokens or `done`.
- Styling uses the Night Desk tokens already in `frontend/tailwind.config.ts` (`ink-*`, `paper*`, `amber-glow`, `gain`, `loss`).
- Run backend commands from `backend/` with `.venv/bin/python -m pytest`; frontend commands from `frontend/`.

## Review Focus

1. **Legacy reports whose metadata price disagrees with the report text** (NIO `00000000-0000`: metadata 5.10, report says $4.88) → visuals use the report's own `**Current Price:**`. Pinned in Task 2 (`test_current_price_*`) and Task 4 (`test_build_insights_prefers_report_price`).
2. **Legs tables with summary rows and signed premiums** (`| — | — | Net Credit | … | **+$0.14/share** |`, `+$0.31`, `-$0.18`) → summary row skipped, premiums unsigned, action decides direction. Pinned in Task 3 (`test_strategy_nio_signed_premiums_and_summary_row`).
3. **Key-level rows holding ranges or several values** (`~$5.50–$6.00`, `$5.40 / $5.74–$5.84`) → that row dropped, the rest of the table kept. Pinned in Task 2 (`test_key_levels_drop_ranges_and_current_row`).
4. **"Poor Man's Covered Call" (name contains "covered call") with legs on different expirations** → no payoff, no stock leg. Pinned in Task 3 (`test_strategy_pmcc_mixed_expirations_is_none`).
5. **Hard-split sections** (a legs row cut across chunk 4 → 5 with 100-char overlap) → re-assembled exactly, not duplicated or broken. Pinned in Task 2 (`test_report_text_undoes_window_overlap`).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/pinecone_client.py` (modify) | Run index cache, `latest_run_chunks`, `run_metadata` |
| `backend/src/insights.py` (create) | Table parsing, payoff math, score/trend shaping, `build_insights` orchestration |
| `backend/src/routes/chat.py` (modify) | Submit builder to thread pool; emit `insights` event |
| `backend/tests/test_pinecone_client.py` (modify) | Run index / fetch helpers tests |
| `backend/tests/test_insights.py` (create) | Parser, payoff, relevance tests with real-report fixtures |
| `backend/tests/test_chat_stream.py` (modify) | Event emission + failure isolation tests; autouse stub |
| `frontend/lib/types.ts` (modify) | `Insights` types; `Message.insights` |
| `frontend/lib/chart.ts` + `chart.test.ts` (create) | Pure scale/format/colour helpers |
| `frontend/components/ChatWindow.tsx` (modify) | Handle `insights` SSE event |
| `frontend/components/insights/*.tsx` (create) | `InsightCard`, `Sparkline`, `ScoreCard`, `TrendCard`, `IvCard`, `ExpectedMoveCard`, `KeyLevelsCard`, `PayoffCard`, `InsightsPanel` |
| `frontend/components/MessageBubble.tsx` (modify) | Render `InsightsPanel` |

---

### Task 1: Pinecone run index, `latest_run_chunks`, `run_metadata`

**Files:**
- Modify: `backend/src/pinecone_client.py` (replace `_latest_dates_cached` / `_latest_dates`; add helpers after them)
- Test: `backend/tests/test_pinecone_client.py`

**Interfaces:**
- Consumes: existing `_list_ids(index, prefix, namespace)`, `_normalize(v)`, `_get_index()`, `_get_namespace()`, `UnknownSchemaVersionError`.
- Produces:
  - `_run_index_cached(ticker: str, _bucket: int) -> dict[str, dict[str, list[str]]]` (lru_cache; `{report_type: {run_ts: [ids]}}`, undated runs excluded)
  - `_latest_dates(ticker: str) -> dict[str, str]` (unchanged signature)
  - `latest_run_chunks(ticker: str, report_type: str) -> list[dict]` — normalized chunks `{id, score, text, metadata}` of the newest dated run, chunk order
  - `run_metadata(ticker: str, report_type: str, limit: int = 60) -> list[dict]` — metadata dicts (no `text` key), oldest → newest
  - `_run_metadata_cached` (lru_cache, for test `cache_clear()`)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pinecone_client.py` (before the `TestListIdsFlattening` section), and in the existing `TestRetrieveLatestOnly._patch` replace `pc._latest_dates_cached.cache_clear()` with `pc._run_index_cached.cache_clear()`:

```python
class TestRunIndex:
    """Run-level helpers for insights: newest full report + per-run metadata series."""

    IDS = [
        "MARA:OPTIONS:00000000-0000:preamble:0",
        "MARA:OPTIONS:20261002-1311:preamble:0",
        "MARA:OPTIONS:20261003-1311:expected-move:2",
        "MARA:OPTIONS:20261003-1311:preamble:0",
        "MARA:OPTIONS:20261003-1311:volatility-dashboard:1",
        "MARA:ANALYSIS:20261003-1111:summary:0",
    ]

    def _fake_index(self, fetched: list):
        ids = self.IDS

        class FakeIndex:
            def list(self, prefix, namespace):
                yield [i for i in ids if i.startswith(prefix)]

            def fetch(self, ids, namespace):
                fetched.append(list(ids))
                vectors = {}
                for i in ids:
                    ts = i.split(":")[2]
                    vectors[i] = {"id": i, "metadata": {
                        "schema_version": 1,
                        "generated_date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                        "text": i,
                    }}
                return {"vectors": vectors}

        return FakeIndex()

    def _patch(self, monkeypatch: pytest.MonkeyPatch, fetched: list):
        import src.pinecone_client as pc

        pc._run_index_cached.cache_clear()
        pc._run_metadata_cached.cache_clear()
        monkeypatch.setattr(pc, "_get_index", lambda: self._fake_index(fetched))
        monkeypatch.setattr(pc, "_get_namespace", lambda: "trade")
        return pc

    def test_latest_run_chunks_newest_dated_run_in_chunk_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pc = self._patch(monkeypatch, [])
        chunks = pc.latest_run_chunks("mara", "options")
        assert [c["id"] for c in chunks] == [
            "MARA:OPTIONS:20261003-1311:preamble:0",
            "MARA:OPTIONS:20261003-1311:volatility-dashboard:1",
            "MARA:OPTIONS:20261003-1311:expected-move:2",
        ]

    def test_undated_runs_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pc = self._patch(monkeypatch, [])
        assert pc._latest_dates("MARA") == {"OPTIONS": "2026-10-03", "ANALYSIS": "2026-10-03"}
        meta = pc.run_metadata("MARA", "OPTIONS")
        assert [m["generated_date"] for m in meta] == ["2026-10-02", "2026-10-03"]
        assert all("text" not in m for m in meta)

    def test_run_metadata_uses_first_chunk_and_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fetched: list = []
        pc = self._patch(monkeypatch, fetched)
        meta = pc.run_metadata("MARA", "OPTIONS", limit=1)
        assert [m["generated_date"] for m in meta] == ["2026-10-03"]
        assert fetched == [["MARA:OPTIONS:20261003-1311:preamble:0"]]

    def test_unknown_type_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pc = self._patch(monkeypatch, [])
        assert pc.latest_run_chunks("MARA", "TECHNICAL") == []
        assert pc.run_metadata("MARA", "TECHNICAL") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_pinecone_client.py`
Expected: FAIL — `AttributeError: module 'src.pinecone_client' has no attribute '_run_index_cached'`.

- [ ] **Step 3: Implement**

In `backend/src/pinecone_client.py`, replace the block from `@lru_cache(maxsize=256)\ndef _latest_dates_cached` through the end of `_latest_dates` with:

```python
_UNDATED = "00000000"  # legacy runs with no timestamp in their ID; never "latest"


def _ttl_bucket() -> int:
    return int(time.monotonic() // _LATEST_TTL_S)


@lru_cache(maxsize=256)
def _run_index_cached(ticker: str, _bucket: int) -> dict[str, dict[str, list[str]]]:
    """{report_type: {run_ts: [chunk ids]}} for every dated run of a ticker.
    Shared by the cache — callers must not mutate it."""
    runs: dict[str, dict[str, list[str]]] = {}
    for vid in _list_ids(_get_index(), f"{ticker}:", _get_namespace()):
        parts = vid.split(":")  # <TICKER>:<TYPE>:<YYYYMMDD-HHMM>:<slug>:<n>
        if len(parts) < 5 or len(parts[2]) < 8 or parts[2].startswith(_UNDATED):
            continue
        runs.setdefault(parts[1], {}).setdefault(parts[2], []).append(vid)
    return runs


def _run_index(ticker: str) -> dict[str, dict[str, list[str]]]:
    return _run_index_cached(ticker.upper(), _ttl_bucket())


def _latest_dates(ticker: str) -> dict[str, str]:
    """{report_type: newest generated_date} for a ticker, from the sortable ID scheme."""
    latest: dict[str, str] = {}
    for rtype, runs in _run_index(ticker).items():
        ts = max(runs)
        latest[rtype] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    return latest


def _chunk_no(vid: str) -> int:
    tail = vid.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _fetch_normalized(ids: list[str]) -> list[dict]:
    """Fetch IDs in batches of 100 and normalize, keeping `ids` order."""
    index, namespace = _get_index(), _get_namespace()
    out: list[dict] = []
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        res = index.fetch(ids=batch, namespace=namespace)
        vectors = res.get("vectors", {}) if isinstance(res, dict) else (getattr(res, "vectors", None) or {})
        for vid in batch:
            if vid not in vectors:
                continue
            try:
                out.append(_normalize(vectors[vid]))
            except UnknownSchemaVersionError as exc:
                logger.error("fetch: skipping record with unknown schema: %s", exc)
    return out


def latest_run_chunks(ticker: str, report_type: str) -> list[dict]:
    """All chunks of the newest dated run of `report_type`, in chunk order; [] if none."""
    runs = _run_index(ticker).get(report_type.upper())
    if not runs:
        return []
    return _fetch_normalized(sorted(runs[max(runs)], key=_chunk_no))


@lru_cache(maxsize=256)
def _run_metadata_cached(ticker: str, report_type: str, limit: int, _bucket: int) -> list[dict]:
    runs = _run_index(ticker).get(report_type, {})
    firsts = [min(runs[ts], key=_chunk_no) for ts in sorted(runs)[-limit:]]
    return [
        {k: v for k, v in c["metadata"].items() if k != "text"}
        for c in _fetch_normalized(firsts)
    ]


def run_metadata(ticker: str, report_type: str, limit: int = 60) -> list[dict]:
    """Metadata (no text) of the first chunk of each of the newest `limit` dated runs,
    oldest → newest. Shared by the cache — callers must not mutate it."""
    return _run_metadata_cached(ticker.upper(), report_type.upper(), limit, _ttl_bucket())
```

Keep the existing `# ponytail:` comment and `_LATEST_TTL_S = 600` above this block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_pinecone_client.py`
Expected: all pass (including the existing `TestRetrieveLatestOnly`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/pinecone_client.py backend/tests/test_pinecone_client.py
git commit -m "feat(insights): run index, latest_run_chunks and run_metadata"
```

---

### Task 2: Report text re-assembly and table parsers

**Files:**
- Create: `backend/src/insights.py`
- Test: `backend/tests/test_insights.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all in `src.insights`):
  - `report_text(chunks: list[dict]) -> str`
  - `parse_current_price(text: str) -> float | None`
  - `parse_expected_move(text: str, price: float) -> dict | None` → `{"price", "ranges": [{"label", "low", "high", "pct", "approx"}]}`
  - `parse_key_levels(text: str, price: float) -> dict | None` → `{"price", "levels": [{"label", "price", "note", "approx"}]}` sorted high → low
  - internal helpers `_tables`, `_num`, `_range`, `_label`, `_col` used by Task 3

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_insights.py`:

```python
"""
test_insights.py — grounded-visuals builder (spec 2026-10-03-report-insights-visuals-design).

Fixtures are excerpts copied from real stored reports (MARA 2026-10-03, legacy NIO,
VDY, CLOV) so parser tests pin the producer's actual table formats.
"""

from __future__ import annotations

import pytest

from src import insights

MARA_OPTIONS = """# Options Analysis: MARA — MARA Holdings Inc

**Generated:** 2026-10-03 13:11 EDT
**Current Price:** $11.23 USD | **Market Cap:** ~$2.1B

---
## Expected Move

| Timeframe | Expected Move ($) | Expected Move (%) | Range |
|-----------|------------------|--------------------|-------|
| Next Week | +/- $2.35 | +/- 20.9% | $8.88 — $13.58 |
| Next Month | +/- $4.80 | +/- 42.7% | $6.43 — $16.03 |
| Next 90 Days | +/- $7.20 | +/- 64.1% | $4.03 — $18.43 |

---
## Recommended Strategies

### Strategy 1: Collar — RECOMMENDED (HEDGE)

| Leg | Action | Strike | Expiration | Type | Price |
|-----|--------|--------|------------|------|-------|
| 1 | Buy | $10.00 | Nov 21, 2026 | Put | ~$1.55 |
| 2 | Sell | $13.00 | Nov 21, 2026 | Call | ~$1.35 |

| Metric | Value |
|--------|-------|
| Net Cost | ~$0.20/share |

---

### Strategy 3: Bear Put Spread (DEFINED RISK HEDGE)
| Leg | Action | Strike | Expiry | Type | Price |
|-----|--------|--------|--------|------|-------|
| 1 | Buy | $11.00 | Nov 21 | Put | ~$2.20 |
| 2 | Sell | $8.00 | Nov 21 | Put | ~$0.80 |

---
## Key Levels for Options Traders
| Level | Price | Significance |
|-------|-------|-------------|
| Max Pain (Oct) | $10.00 | Options market equilibrium |
| 52-Week High | $23.45 | Major resistance |
| 52-Week Low | $6.66 | Key support level |
| Expected Move High | $16.03 | 1-sigma upside |
| Expected Move Low | $6.43 | 1-sigma downside |
| Technical Support | $9.00 | Prior base |
"""

NIO_LEGACY = """# Options Analysis: NIO

**Current Price:** $4.88

## Expected Move

| Timeframe | Expected Move ($) | Expected Move (%) | Range |
|-----------|------------------|--------------------|-------|
| Next Week (7 days) | +/- $0.39 | +/- 8.0% | $4.49 — $5.27 |
| Next Month (30 days) | +/- $0.81 | +/- 16.6% | $4.07 — $5.69 |
| Into Earnings (61 days) | +/- $1.16 | +/- 23.7% | $3.72 — $6.04 |
| Next 90 Days | +/- $1.41 | +/- 28.8% | $3.47 — $6.29 |

| Quarter | Implied Move | Actual Move | Beat/Miss | Direction |
|---------|-------------|-------------|-----------|-----------|
| Q1 2026 (May 21) | ~+/- 18% | ~-9% | Deliveries beat | Down |

## Recommended Strategies

### Strategy 1: Collar — $5.00 Call / $4.50 Put (Aug 15) — RECOMMENDED ✦ HEDGE

| Leg | Action | Strike | Expiration | Type | Est. Price |
|-----|--------|--------|------------|------|-----------|
| 1 | Sell | $5.00 | Aug 15, 2026 | Call | +$0.31 |
| 2 | Buy | $4.50 | Aug 15, 2026 | Put | -$0.18 |
| — | — | Net Credit | — | — | **+$0.14/share** |

## Key Levels for Options Traders

| Level | Price | Significance |
|-------|-------|-------------|
| Max Pain (Jul 18, est.) | ~$5.00 | Options market equilibrium — mild gravitational pull |
| Call Wall (est.) | ~$5.50–$6.00 | Heavy call OI creates resistance |
| Put Wall (est.) | ~$4.00 | Elevated put OI provides some support |
| Expected Move High (1 month) | $5.69 | 1-sigma upside |
| Expected Move Low (1 month) | $4.07 | 1-sigma downside |
| 52-Week Low | $3.38 | Catastrophic support; structural floor |
| Technical Resistance | $5.40 / $5.74–$5.84 | Chart-based resistance zones |
| Current Price | $4.88 | Just below the $4.89 support cluster |
"""

CLOV_PMCC = """**Current Price:** $4.38

## Recommended Strategies

### Strategy 1: Poor Man's Covered Call (PMCC) — RECOMMENDED (INCOME)

| Leg | Action | Strike | Expiration | Type | Price |
|-----|--------|--------|------------|------|-------|
| 1 (Anchor) | Buy | $3.00 | Jan 16, 2027 | Call | ~$1.65 |
| 2 (Income) | Sell | $5.00 | Oct 17, 2026 | Call | ~$0.28 |
"""

VDY_OPTIONS = """# Options Analysis: VDY — Vanguard FTSE Canadian High Dividend Yield ETF

**Current Price:** CAD $75.75 | **AUM:** ~CAD $7B+

## Options Availability Assessment

**VDY.TO does not have a liquid listed options market.**
"""


class TestReportText:
    def test_report_text_undoes_window_overlap(self) -> None:
        # Mirror trade_memory._chunk_by_section: 1500-char windows, 100-char overlap.
        head = "# Title\n\n**Current Price:** $11.23"
        long_section = "## Recommended Strategies\n" + "".join(f"| {i} | Buy | $1{i % 10}.00 |\n" for i in range(120))
        tail = "## Key Levels\n| Level | Price |"
        windows = [long_section[s:s + 1500] for s in range(0, len(long_section), 1400)]
        chunks = [{"text": head, "metadata": {"section": "preamble"}}]
        chunks += [{"text": w, "metadata": {"section": "recommended-strategies"}} for w in windows]
        chunks += [{"text": tail, "metadata": {"section": "key-levels"}}]
        assert len(windows) > 1
        assert insights.report_text(chunks) == "\n".join([head, long_section, tail])

    def test_report_text_keeps_short_same_slug_sections(self) -> None:
        chunks = [
            {"text": "## Notes\nfirst", "metadata": {"section": "notes"}},
            {"text": "## Notes\nsecond", "metadata": {"section": "notes"}},
        ]
        assert insights.report_text(chunks) == "## Notes\nfirst\n## Notes\nsecond"


class TestCurrentPrice:
    def test_current_price_from_report_text(self) -> None:
        assert insights.parse_current_price(MARA_OPTIONS) == 11.23
        assert insights.parse_current_price(NIO_LEGACY) == 4.88

    def test_current_price_with_currency_code(self) -> None:
        assert insights.parse_current_price(VDY_OPTIONS) == 75.75

    def test_current_price_missing(self) -> None:
        assert insights.parse_current_price("no price here") is None


class TestExpectedMove:
    def test_expected_move_mara(self) -> None:
        em = insights.parse_expected_move(MARA_OPTIONS, 11.23)
        assert em["price"] == 11.23
        assert em["ranges"][0] == {
            "label": "Next Week", "low": 8.88, "high": 13.58, "pct": 20.9, "approx": False,
        }
        assert [r["label"] for r in em["ranges"]] == ["Next Week", "Next Month", "Next 90 Days"]

    def test_expected_move_ignores_other_tables(self) -> None:
        em = insights.parse_expected_move(NIO_LEGACY, 4.88)
        assert [r["label"] for r in em["ranges"]] == [
            "Next Week (7 days)", "Next Month (30 days)", "Into Earnings (61 days)", "Next 90 Days",
        ]

    def test_expected_move_missing(self) -> None:
        assert insights.parse_expected_move(VDY_OPTIONS, 75.75) is None


class TestKeyLevels:
    def test_key_levels_sorted_high_to_low(self) -> None:
        kl = insights.parse_key_levels(MARA_OPTIONS, 11.23)
        assert [lv["price"] for lv in kl["levels"]] == [23.45, 16.03, 10.0, 9.0, 6.66, 6.43]
        assert kl["levels"][2] == {
            "label": "Max Pain (Oct)", "price": 10.0, "note": "Options market equilibrium", "approx": False,
        }

    def test_key_levels_drop_ranges_and_current_row(self) -> None:
        kl = insights.parse_key_levels(NIO_LEGACY, 4.88)
        labels = [lv["label"] for lv in kl["levels"]]
        assert "Call Wall (est.)" not in labels
        assert "Technical Resistance" not in labels
        assert "Current Price" not in labels
        assert [lv["price"] for lv in kl["levels"]] == [5.69, 5.0, 4.07, 4.0, 3.38]
        assert kl["levels"][1]["approx"] is True

    def test_key_levels_drop_implausible_prices(self) -> None:
        text = "| Level | Price | Significance |\n|---|---|---|\n| Typo | $1123.00 | x |\n| Support | $10.00 | y |"
        kl = insights.parse_key_levels(text, 11.23)
        assert [lv["price"] for lv in kl["levels"]] == [10.0]

    def test_key_levels_missing(self) -> None:
        assert insights.parse_key_levels(VDY_OPTIONS, 75.75) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py`
Expected: FAIL — `ImportError: cannot import name 'insights' from 'src'`.

- [ ] **Step 3: Implement**

Create `backend/src/insights.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/insights.py backend/tests/test_insights.py
git commit -m "feat(insights): report re-assembly and expected-move/key-level parsers"
```

---

### Task 3: Strategy legs parser and payoff math

**Files:**
- Modify: `backend/src/insights.py` (append)
- Test: `backend/tests/test_insights.py` (append)

**Interfaces:**
- Consumes: `_tables`, `_num`, `_label`, `_col` (Task 2); fixtures `MARA_OPTIONS`, `NIO_LEGACY`, `CLOV_PMCC` (Task 2 test file).
- Produces:
  - `payoff(legs: list[dict], price: float, includes_stock: bool) -> dict` → `{"curve": [[x, y]], "breakevens": [float], "max_gain": float | None, "max_loss": float | None}`
  - `parse_strategy(text: str, price: float) -> dict | None` → `{"name", "expiration", "includes_stock", "price", "legs": [{"action", "type", "strike", "premium", "approx"}], **payoff}`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_insights.py`:

```python
def _leg(action: str, kind: str, strike: float, premium: float) -> dict:
    return {"action": action, "type": kind, "strike": strike, "premium": premium, "approx": False}


class TestPayoff:
    def test_collar_reference_values(self) -> None:
        # Spec §5 reference: MARA collar 2026-10-03.
        p = insights.payoff([_leg("buy", "put", 10.0, 1.55), _leg("sell", "call", 13.0, 1.35)], 11.23, True)
        assert p["max_loss"] == -1.43
        assert p["max_gain"] == 1.57
        assert p["breakevens"] == [11.43]

    def test_bear_put_spread_without_stock(self) -> None:
        p = insights.payoff([_leg("buy", "put", 11.0, 2.20), _leg("sell", "put", 8.0, 0.80)], 11.23, False)
        assert (p["max_gain"], p["max_loss"], p["breakevens"]) == (1.6, -1.4, [9.6])

    def test_covered_call(self) -> None:
        p = insights.payoff([_leg("sell", "call", 5.50, 0.30)], 5.10, True)
        assert (p["max_gain"], p["max_loss"], p["breakevens"]) == (0.7, -4.8, [4.8])

    def test_unbounded_sides(self) -> None:
        assert insights.payoff([_leg("buy", "call", 10.0, 1.0)], 10.0, False)["max_gain"] is None
        assert insights.payoff([_leg("sell", "call", 10.0, 1.0)], 10.0, False)["max_loss"] is None

    def test_curve_is_bounded_and_covers_price(self) -> None:
        p = insights.payoff([_leg("buy", "put", 10.0, 1.55), _leg("sell", "call", 13.0, 1.35)], 11.23, True)
        xs = [x for x, _ in p["curve"]]
        assert len(p["curve"]) <= 80
        assert xs == sorted(xs) and xs[0] < 10.0 and xs[-1] > 13.0
        assert [10.0, -1.43] in p["curve"] and [13.0, 1.57] in p["curve"]


class TestStrategy:
    def test_strategy_mara_collar(self) -> None:
        s = insights.parse_strategy(MARA_OPTIONS, 11.23)
        assert s["name"] == "Collar"
        assert s["expiration"] == "Nov 21, 2026"
        assert s["includes_stock"] is True
        assert s["legs"] == [
            {"action": "buy", "type": "put", "strike": 10.0, "premium": 1.55, "approx": True},
            {"action": "sell", "type": "call", "strike": 13.0, "premium": 1.35, "approx": True},
        ]
        assert (s["max_loss"], s["max_gain"], s["breakevens"]) == (-1.43, 1.57, [11.43])

    def test_strategy_nio_signed_premiums_and_summary_row(self) -> None:
        s = insights.parse_strategy(NIO_LEGACY, 4.88)
        assert s["name"] == "Collar"
        assert [(leg["action"], leg["premium"]) for leg in s["legs"]] == [("sell", 0.31), ("buy", 0.18)]
        assert (s["max_loss"], s["max_gain"], s["breakevens"]) == (-0.25, 0.25, [4.75])

    def test_strategy_expiry_and_est_price_headers(self) -> None:
        text = (
            "### Strategy 1: Bear Put Spread — HEDGE\n\n"
            "| Leg | Action | Strike | Expiry | Type | Price (est.) |\n"
            "|---|---|---|---|---|---|\n"
            "| 1 | Buy | $11.00 | Nov 21 | Put | ~$2.20 |\n"
            "| 2 | Sell | $8.00 | Nov 21 | Put | ~$0.80 |\n"
        )
        s = insights.parse_strategy(text, 11.23)
        assert s["includes_stock"] is False
        assert (s["max_gain"], s["max_loss"]) == (1.6, -1.4)

    def test_strategy_pmcc_mixed_expirations_is_none(self) -> None:
        assert insights.parse_strategy(CLOV_PMCC, 4.38) is None

    def test_strategy_only_reads_strategy_1_section(self) -> None:
        text = (
            "### Strategy 1: Collar — HEDGE\n\nNo legs table here.\n\n"
            "### Strategy 2: Bear Put Spread\n"
            "| Leg | Action | Strike | Expiration | Type | Price |\n|---|---|---|---|---|---|\n"
            "| 1 | Buy | $11.00 | Nov 21 | Put | $2.20 |\n"
        )
        assert insights.parse_strategy(text, 11.23) is None

    def test_strategy_missing(self) -> None:
        assert insights.parse_strategy(VDY_OPTIONS, 75.75) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py -k "Payoff or Strategy"`
Expected: FAIL — `AttributeError: module 'src.insights' has no attribute 'payoff'`.

- [ ] **Step 3: Implement**

Append to `backend/src/insights.py`:

```python
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
        i_px = next((i for i, h in enumerate(header) if "price" in h), None)
        if None in (i_act, i_strike, i_type, i_exp, i_px):
            continue
        legs: list[dict] = []
        expirations: set[str] = set()
        for row in rows:
            if len(row) != len(header):
                continue
            action, kind = row[i_act].lower(), row[i_type].lower()
            strike, premium = _num(row[i_strike]), _num(row[i_px])
            if action not in ("buy", "sell") or kind not in ("call", "put") or strike is None or premium is None:
                continue
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/insights.py backend/tests/test_insights.py
git commit -m "feat(insights): strategy legs parser and at-expiry payoff"
```

---

### Task 4: Score card, trend series, `build_insights` orchestration

**Files:**
- Modify: `backend/src/insights.py` (append; add `import src.pinecone_client as pc` and `from typing import Any, Optional`)
- Test: `backend/tests/test_insights.py` (append)

**Interfaces:**
- Consumes: `pc.latest_run_chunks`, `pc.run_metadata` (Task 1); `report_text`, `parse_current_price`, `parse_expected_move`, `parse_key_levels`, `parse_strategy` (Tasks 2–3).
- Produces:
  - `score_card(meta: dict) -> dict | None`
  - `trend(analysis_runs: list[dict], options_runs: list[dict], focus: bool) -> dict | None` → `{"points": [...], "focus": bool}`
  - `build_insights(ticker: str | None, context_types: set, intent: str) -> dict | None` → `{"ticker", "score"?, "trend"?, "iv"?, "expected_move"?, "key_levels"?, "strategy"?}`; every section except `trend` carries `"source": {"source_path", "generated_date"}`. Never raises.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_insights.py`:

```python
MARA_ANALYSIS_META = {
    "composite_score": 29, "grade": "D", "signal": "CAUTION",
    "technical_score": 28, "fundamental_score": 27, "sentiment_score": 32,
    "risk_score": 27, "thesis_score": 33,
    "price_at_analysis": 11.23, "stop_loss": 9.8, "nearest_catalyst_date": "2026-11-05",
    "generated_date": "2026-10-03", "source_path": "TRADE-ANALYSIS-MARA.md", "report_type": "ANALYSIS",
}


class TestScoreAndTrend:
    def test_score_card_from_metadata(self) -> None:
        s = insights.score_card(MARA_ANALYSIS_META)
        assert (s["composite"], s["grade"], s["signal"]) == (29, "D", "CAUTION")
        assert [d["score"] for d in s["dimensions"]] == [28, 27, 32, 27, 33]
        assert round(sum(d["weight"] for d in s["dimensions"]), 6) == 1.0
        assert (s["price"], s["stop_loss"], s["catalyst_date"]) == (11.23, 9.8, "2026-11-05")
        assert s["source"] == {"source_path": "TRADE-ANALYSIS-MARA.md", "generated_date": "2026-10-03"}

    def test_score_card_needs_composite(self) -> None:
        assert insights.score_card({"grade": "D"}) is None

    def test_trend_merges_by_date_analysis_price_wins(self) -> None:
        analysis = [
            {"generated_date": "2026-10-02", "price_at_analysis": 11.0, "composite_score": 25, "signal": "CAUTION"},
            {"generated_date": "2026-10-03", "price_at_analysis": 11.23, "composite_score": 29, "signal": "CAUTION"},
        ]
        options = [
            {"generated_date": "2026-10-01", "price_at_analysis": 12.0, "iv_rank": 40, "signal": "NEUTRAL"},
            {"generated_date": "2026-10-03", "price_at_analysis": 11.5, "iv_rank": 32, "signal": "CAUTION"},
        ]
        t = insights.trend(analysis, options, focus=True)
        assert t["focus"] is True
        assert [p["date"] for p in t["points"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
        assert t["points"][2] == {"date": "2026-10-03", "price": 11.23, "score": 29, "iv_rank": 32, "signal": "CAUTION"}
        assert t["points"][0] == {"date": "2026-10-01", "price": 12.0, "iv_rank": 40, "signal": "NEUTRAL"}

    def test_trend_needs_two_points(self) -> None:
        assert insights.trend([{"generated_date": "2026-10-03", "composite_score": 29}], [], focus=False) is None


class TestBuildInsights:
    @pytest.fixture
    def fake_pc(self, monkeypatch: pytest.MonkeyPatch):
        options_meta = {"report_type": "OPTIONS", "iv_rank": 32, "price_at_analysis": 99.0,
                        "generated_date": "2026-10-03", "source_path": "TRADE-OPTIONS-MARA-20261003-1311.md",
                        "section": "x"}
        runs = {
            "ANALYSIS": [dict(MARA_ANALYSIS_META, generated_date="2026-10-02"), MARA_ANALYSIS_META],
            "OPTIONS": [dict(options_meta, generated_date="2026-10-02"), options_meta],
        }
        monkeypatch.setattr(insights.pc, "run_metadata", lambda t, rt, limit=60: runs.get(rt, []))
        monkeypatch.setattr(
            insights.pc, "latest_run_chunks",
            lambda t, rt: [{"text": MARA_OPTIONS, "metadata": options_meta}] if rt == "OPTIONS" else [],
        )

    def test_analysis_context_gives_score_and_trend(self, fake_pc) -> None:
        out = insights.build_insights("MARA", {"ANALYSIS"}, "factual")
        assert set(out) == {"ticker", "score", "trend"}
        assert out["trend"]["focus"] is False

    def test_options_context_gives_options_sections(self, fake_pc) -> None:
        out = insights.build_insights("MARA", {"OPTIONS"}, "factual")
        assert set(out) == {"ticker", "iv", "expected_move", "key_levels", "strategy", "trend"}
        assert out["iv"]["iv_rank"] == 32
        assert out["strategy"]["source"]["source_path"] == "TRADE-OPTIONS-MARA-20261003-1311.md"

    def test_build_insights_prefers_report_price(self, fake_pc) -> None:
        # metadata says 99.0, report text says $11.23 → visuals use the report.
        out = insights.build_insights("MARA", {"OPTIONS"}, "factual")
        assert out["expected_move"]["price"] == 11.23
        assert out["strategy"]["max_loss"] == -1.43

    def test_trajectory_gives_focused_trend(self, fake_pc) -> None:
        out = insights.build_insights("MARA", set(), "trajectory")
        assert set(out) == {"ticker", "trend"}
        assert out["trend"]["focus"] is True

    def test_no_ticker_or_nothing_relevant(self, fake_pc) -> None:
        assert insights.build_insights(None, {"ANALYSIS"}, "factual") is None
        assert insights.build_insights("MARA", set(), "factual") is None

    def test_one_failing_section_keeps_the_rest(self, fake_pc, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a, **kw):
            raise ValueError("bad table")
        monkeypatch.setattr(insights, "parse_key_levels", boom)
        out = insights.build_insights("MARA", {"OPTIONS"}, "factual")
        assert "key_levels" not in out and "expected_move" in out and "strategy" in out

    def test_pinecone_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def down(*a, **kw):
            raise ConnectionError("pinecone down")
        monkeypatch.setattr(insights.pc, "run_metadata", down)
        monkeypatch.setattr(insights.pc, "latest_run_chunks", down)
        assert insights.build_insights("MARA", {"ANALYSIS", "OPTIONS"}, "factual") is None

    def test_no_liquid_options_gives_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {"report_type": "OPTIONS", "iv_rank": None, "generated_date": "2026-10-03",
                "source_path": "TRADE-OPTIONS-VDY.md"}
        monkeypatch.setattr(insights.pc, "run_metadata", lambda *a, **kw: [])
        monkeypatch.setattr(insights.pc, "latest_run_chunks", lambda t, rt: [{"text": VDY_OPTIONS, "metadata": meta}])
        assert insights.build_insights("VDY", {"OPTIONS"}, "factual") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py -k "ScoreAndTrend or BuildInsights"`
Expected: FAIL — `AttributeError: module 'src.insights' has no attribute 'score_card'` (and `pc`).

- [ ] **Step 3: Implement**

In `backend/src/insights.py`, change the typing import to `from typing import Any, Optional` and add below it:

```python
import src.pinecone_client as pc
```

Append:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_insights.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/insights.py backend/tests/test_insights.py
git commit -m "feat(insights): score card, trend series and build_insights relevance"
```

---

### Task 5: Emit `insights` from `/chat/stream`

**Files:**
- Modify: `backend/src/routes/chat.py` (imports; helper above `post_chat`; generator after the quote block; token loop; after loop; module docstring)
- Modify: `backend/tests/conftest.py` (autouse offline stub)
- Test: `backend/tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `build_insights(ticker, context_types, intent)` (Task 4).
- Produces: SSE event `{"event": "insights", "data": <json>}` at most once between `citations` and `done`; module attrs `_INSIGHTS_POOL`, `_INSIGHTS_WAIT_S`, `_insights_event(future, timeout=0)`.

- [ ] **Step 1: Write the failing tests**

`test_chat_stream.py`, `test_auth.py` and `test_rate_limiter.py` all stream with chunks, and `.env` holds a real Pinecone key, so keep every test offline with an autouse stub. Append to `backend/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_live_insights(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route's insights builder reads live Pinecone; stub it for every test.
    Tests that exercise insights override it with their own monkeypatch."""
    monkeypatch.setattr("src.routes.chat.build_insights", lambda *a, **kw: None)
```

Append these tests at the end of `backend/tests/test_chat_stream.py`:

```python
# ---------------------------------------------------------------------------
# Insights (spec 2026-10-03-report-insights-visuals-design)
# ---------------------------------------------------------------------------

_FAKE_INSIGHTS = {"ticker": "AAPL", "score": {"composite": 82, "grade": "A", "signal": "BUY"}}


def test_stream_emits_insights_between_citations_and_done(client, auth_headers, monkeypatch):
    calls: list = []

    def _build(ticker, context_types, intent):
        calls.append((ticker, set(context_types), intent))
        return _FAKE_INSIGHTS

    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))
    monkeypatch.setattr("src.routes.chat.build_insights", _build)

    resp = client.post("/chat/stream", headers=auth_headers, json={"message": "bull case for AAPL", "ticker": "AAPL"})
    events = _parse_sse_events(resp.content)
    names = [e["event"] for e in events]

    assert names.count("insights") == 1
    assert names.index("citations") < names.index("insights") < names.index("done")
    assert names[-1] == "done"
    assert json.loads(events[names.index("insights")]["data"]) == _FAKE_INSIGHTS
    assert calls == [("AAPL", {"ANALYSIS"}, "factual")]


def test_stream_insights_failure_keeps_answer(client, auth_headers, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("builder exploded")

    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))
    monkeypatch.setattr("src.routes.chat.build_insights", _boom)

    resp = client.post("/chat/stream", headers=auth_headers, json={"message": "bull case for AAPL", "ticker": "AAPL"})
    events = _parse_sse_events(resp.content)
    names = [e["event"] for e in events]

    assert "insights" not in names and "error" not in names
    assert "".join(e["data"] for e in events if e["event"] == "token") == "".join(_FAKE_TOKENS)
    assert names[-1] == "done"


def test_stream_no_insights_event_when_nothing_built(client, auth_headers, monkeypatch):
    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))

    resp = client.post("/chat/stream", headers=auth_headers, json={"message": "bull case for AAPL", "ticker": "AAPL"})
    assert "insights" not in [e["event"] for e in _parse_sse_events(resp.content)]


def test_stream_waits_briefly_for_slow_insights(client, auth_headers, monkeypatch):
    import time

    def _slow(*a, **kw):
        time.sleep(0.2)
        return _FAKE_INSIGHTS

    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))
    monkeypatch.setattr("src.routes.chat.build_insights", _slow)

    resp = client.post("/chat/stream", headers=auth_headers, json={"message": "bull case for AAPL", "ticker": "AAPL"})
    names = [e["event"] for e in _parse_sse_events(resp.content)]
    assert names.index("insights") < names.index("done")


def test_stream_drops_insights_past_the_wait_budget(client, auth_headers, monkeypatch):
    import time

    def _too_slow(*a, **kw):
        time.sleep(0.5)
        return _FAKE_INSIGHTS

    monkeypatch.setattr("src.routes.chat.retrieve", lambda *a, **kw: _FAKE_CHUNKS)
    monkeypatch.setattr("src.routes.chat.stream_complete", _make_stream_mock(_FAKE_TOKENS))
    monkeypatch.setattr("src.routes.chat.build_insights", _too_slow)
    monkeypatch.setattr("src.routes.chat._INSIGHTS_WAIT_S", 0.05)

    resp = client.post("/chat/stream", headers=auth_headers, json={"message": "bull case for AAPL", "ticker": "AAPL"})
    names = [e["event"] for e in _parse_sse_events(resp.content)]
    assert "insights" not in names and names[-1] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest -q tests/test_chat_stream.py`
Expected: FAIL — `AttributeError: <module 'src.routes.chat'> does not have the attribute 'build_insights'`.

- [ ] **Step 3: Implement**

In `backend/src/routes/chat.py`:

(a) Module docstring — directly below the line `       event: quote      (JSON quote dict — ONLY for price-intent requests, slice 7)` add:

```
       event: insights   (JSON visuals payload — optional, at most once, anywhere
                          between citations and done; built from report data only)
```

(b) Imports — add `from concurrent.futures import Future, ThreadPoolExecutor` after `import uuid`, and `from src.insights import build_insights` after `from src.intent_classifier import classify_intent`.

(c) Above `def post_chat(`, add:

```python
# Insights (spec 2026-10-03): grounded visuals built off the token path, alongside
# the LLM call, so they never delay the first token.
_INSIGHTS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="insights")
_INSIGHTS_WAIT_S = 2.0


def _insights_event(future: Future, timeout: float = 0) -> dict | None:
    """The `insights` SSE event once the builder finished; None if it failed, timed
    out or had nothing to show. Never raises — visuals can't break the chat."""
    try:
        payload = future.result(timeout=timeout)
    except Exception as exc:
        logger.warning("insights: dropped (%r)", exc)
        return None
    return {"event": "insights", "data": json.dumps(payload)} if payload else None
```

(d) In `post_chat_stream._event_generator`, immediately before the line `        # --- Step 3: Build messages list (history + new grounded user prompt) ---`, add:

```python
        insights_future = _INSIGHTS_POOL.submit(
            build_insights,
            ticker_upper,
            {(c.get("metadata") or {}).get("report_type") for c in chunks},
            intent,
        )
        insights_pending = True
```

(e) Replace the token loop body:

```python
            for token in stream_complete(system=SYSTEM_PROMPT, messages=messages):
                full_response_parts.append(token)
                yield {"event": "token", "data": token}
```

with:

```python
            for token in stream_complete(system=SYSTEM_PROMPT, messages=messages):
                if insights_pending and insights_future.done():
                    insights_pending = False
                    event = _insights_event(insights_future)
                    if event:
                        yield event
                full_response_parts.append(token)
                yield {"event": "token", "data": token}
```

(f) Directly after the `except LLMProviderError ...: ... return` block and before `# --- Step 5: Persist both turns on completion ---`, add:

```python
        if insights_pending:
            event = _insights_event(insights_future, timeout=_INSIGHTS_WAIT_S)
            if event:
                yield event
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: full suite passes (previous 144 + new tests), 7 skipped.

- [ ] **Step 5: Commit**

```bash
git add backend/src/routes/chat.py backend/tests/conftest.py backend/tests/test_chat_stream.py
git commit -m "feat(insights): stream grounded insights event alongside the answer"
```

---

### Task 6: Frontend types, SSE handling, chart helpers

**Files:**
- Modify: `frontend/lib/types.ts`, `frontend/components/ChatWindow.tsx`
- Create: `frontend/lib/chart.ts`, `frontend/lib/chart.test.ts`

**Interfaces:**
- Consumes: SSE `insights` payload shape (Task 4/5).
- Produces (`@/lib/types`): `InsightSource`, `ScoreInsight`, `TrendPoint`, `TrendInsight`, `IvInsight`, `MoveRange`, `ExpectedMoveInsight`, `KeyLevel`, `KeyLevelsInsight`, `StrategyLeg`, `StrategyInsight`, `Insights`; `Message.insights?: Insights`.
  (`@/lib/chart`): `scale(d0,d1,r0,r1)`, `extent(values, pad?)`, `linePath(points)`, `GRADE_BANDS`, `band(score)`, `signalColor(signal)`, `money(n, approx?)`, `signedMoney(n)`, `pctFrom(price, ref)`, `daysUntil(iso, from?)`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/chart.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { band, daysUntil, extent, linePath, money, pctFrom, scale, signalColor, signedMoney } from "./chart";

describe("chart helpers", () => {
  it("scale maps linearly and centres a flat domain", () => {
    const s = scale(0, 10, 100, 200);
    expect(s(0)).toBe(100);
    expect(s(5)).toBe(150);
    expect(scale(3, 3, 0, 10)(3)).toBe(5);
  });

  it("extent pads, handles flat and empty input", () => {
    expect(extent([0, 10], 0.1)).toEqual([-1, 11]);
    expect(extent([5, 5])).toEqual([4, 6]);
    expect(extent([])).toEqual([0, 1]);
  });

  it("linePath breaks on gaps", () => {
    expect(linePath([[0, 1], [1, null], [2, 3], [3, 4]])).toBe("M0.0,1.0M2.0,3.0L3.0,4.0");
  });

  it("band follows the README grade table", () => {
    expect(band(29).grade).toBe("D");
    expect(band(85).grade).toBe("A+");
    expect(band(84).grade).toBe("A");
    expect(band(0).grade).toBe("F");
    expect(signalColor("caution")).toBe(band(30).color);
    expect(signalColor("STRONG BUY")).toBe(band(90).color);
    expect(signalColor(undefined)).toBe("#6d6a63");
  });

  it("formats money, signed money and % distance", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(1.55, true)).toBe("~$1.55");
    expect(signedMoney(-1.43)).toBe("−$1.43");
    expect(signedMoney(1.57)).toBe("+$1.57");
    expect(pctFrom(10, 11.23)).toBe("−11.0%");
    expect(pctFrom(13, 11.23)).toBe("+15.8%");
  });

  it("daysUntil counts whole local days", () => {
    expect(daysUntil("2026-11-05", new Date(2026, 9, 3, 15, 30))).toBe(33);
    expect(daysUntil("not-a-date")).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run lib/chart.test.ts`
Expected: FAIL — cannot resolve `./chart`.

- [ ] **Step 3: Implement**

Create `frontend/lib/chart.ts`:

```ts
/**
 * chart.ts — small pure helpers shared by the insight cards (scales, paths,
 * colours, formatting). No DOM, no dependencies; covered by chart.test.ts.
 */

/** Linear map from domain [d0, d1] to range [r0, r1]; a flat domain maps to the range midpoint. */
export function scale(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0;
  return (v: number) => (span === 0 ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * (r1 - r0));
}

/** [min, max] of the finite values padded by `pad` × span (±1 when flat; [0, 1] when empty). */
export function extent(values: number[], pad = 0.05): [number, number] {
  const xs = values.filter(Number.isFinite);
  if (xs.length === 0) return [0, 1];
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const p = hi === lo ? 1 : (hi - lo) * pad;
  return [lo - p, hi + p];
}

/** SVG path through [x, y] points; a null y lifts the pen (gap in the series). */
export function linePath(points: [number, number | null][]): string {
  let d = "";
  let pen = false;
  for (const [x, y] of points) {
    if (y == null || !Number.isFinite(y)) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** Score → grade/signal bands, mirroring the README table (85+ A+ … 0–24 F). */
export const GRADE_BANDS = [
  { min: 85, grade: "A+", signal: "STRONG BUY", color: "#3ddc97" },
  { min: 70, grade: "A", signal: "BUY", color: "#8fdc5c" },
  { min: 55, grade: "B", signal: "HOLD", color: "#d8c95a" },
  { min: 40, grade: "C", signal: "NEUTRAL", color: "#ffb547" },
  { min: 25, grade: "D", signal: "CAUTION", color: "#ff8a4c" },
  { min: 0, grade: "F", signal: "AVOID", color: "#ff5c6c" },
] as const;

export type GradeBand = (typeof GRADE_BANDS)[number];

export function band(score: number): GradeBand {
  return GRADE_BANDS.find((b) => score >= b.min) ?? GRADE_BANDS[GRADE_BANDS.length - 1];
}

/** Colour for a signal label (case-insensitive); unknown → muted paper. */
export function signalColor(signal: string | null | undefined): string {
  const s = (signal ?? "").toUpperCase();
  return GRADE_BANDS.find((b) => b.signal === s)?.color ?? "#6d6a63";
}

export function money(n: number, approx = false): string {
  const v = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${approx ? "~" : ""}$${v}`;
}

export function signedMoney(n: number): string {
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

/** % distance of `price` from `ref`, e.g. "−11.0%". */
export function pctFrom(price: number, ref: number): string {
  const p = ((price - ref) / ref) * 100;
  return `${p >= 0 ? "+" : "−"}${Math.abs(p).toFixed(1)}%`;
}

/** Whole local days from `from` until an ISO date (YYYY-MM-DD); null if unparseable. */
export function daysUntil(iso: string, from: Date = new Date()): number | null {
  const t = Date.parse(`${iso}T00:00:00`);
  if (Number.isNaN(t)) return null;
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate()).getTime();
  return Math.round((t - start) / 86_400_000);
}
```

In `frontend/lib/types.ts`:

- In the header doc list add ` *   Insights        — grounded report visuals from the SSE insights event`.
- In the `StreamEvent` doc block, after the `2a. event="quote"` line add ` *   2b. event="insights" data=<JSON Insights> (optional, at most once, anywhere before done)`, and change the union to `event: "session" | "citations" | "quote" | "insights" | "token" | "done" | "error" | string;`.
- In `Message` add after `quote?: Quote;`:

```ts
  /** Grounded report visuals, if the backend emitted an insights event for this message. */
  insights?: Insights;
```

- Append:

```ts
/** Provenance shown in each insight card's footer. */
export interface InsightSource {
  source_path: string;
  generated_date: string;
}

export interface ScoreInsight {
  composite: number;
  grade: string | null;
  signal: string | null;
  dimensions: { name: string; score: number; weight: number }[];
  price: number | null;
  stop_loss: number | null;
  catalyst_date: string | null;
  source: InsightSource;
}

export interface TrendPoint {
  date: string;
  price?: number;
  score?: number;
  iv_rank?: number;
  signal?: string;
}

export interface TrendInsight {
  /** Oldest → newest, ≤ 60. */
  points: TrendPoint[];
  /** True for trend questions — render the full TrendCard; else only sparklines. */
  focus: boolean;
}

export interface IvInsight {
  iv_rank: number;
  source: InsightSource;
}

export interface MoveRange {
  label: string;
  low: number;
  high: number;
  pct: number | null;
  approx: boolean;
}

export interface ExpectedMoveInsight {
  price: number;
  ranges: MoveRange[];
  source: InsightSource;
}

export interface KeyLevel {
  label: string;
  price: number;
  note: string | null;
  approx: boolean;
}

export interface KeyLevelsInsight {
  price: number;
  /** Sorted high → low. */
  levels: KeyLevel[];
  source: InsightSource;
}

export interface StrategyLeg {
  action: "buy" | "sell";
  type: "call" | "put";
  strike: number;
  premium: number;
  approx: boolean;
}

export interface StrategyInsight {
  name: string;
  expiration: string;
  includes_stock: boolean;
  price: number;
  legs: StrategyLeg[];
  /** [underlying price at expiry, P/L per share], ascending x. */
  curve: [number, number][];
  breakevens: number[];
  /** null = unbounded. */
  max_gain: number | null;
  max_loss: number | null;
  source: InsightSource;
}

/** Payload of the SSE `insights` event — every value comes from report data, never the LLM. */
export interface Insights {
  ticker: string;
  score?: ScoreInsight;
  trend?: TrendInsight;
  iv?: IvInsight;
  expected_move?: ExpectedMoveInsight;
  key_levels?: KeyLevelsInsight;
  strategy?: StrategyInsight;
}
```

In `frontend/components/ChatWindow.tsx`:

- Header doc: after the `event=quote` line add ` *   event=insights  → attach grounded report visuals to the current assistant message`.
- Import: `import type { Citation, Insights, Message, Quote } from "@/lib/types";`
- Add a case after the `case "quote": {…}` block:

```tsx
          case "insights": {
            // Grounded report visuals (spec 2026-10-03) — malformed JSON is ignored
            let parsedInsights: Insights | undefined;
            try {
              parsedInsights = JSON.parse(event.data) as Insights;
            } catch {
              parsedInsights = undefined;
            }
            if (parsedInsights) {
              updateLastMessage((prev) => ({ ...prev, insights: parsedInsights }));
            }
            break;
          }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all vitest tests pass (6 existing + 6 new); tsc exits 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/chart.ts frontend/lib/chart.test.ts frontend/components/ChatWindow.tsx
git commit -m "feat(insights): frontend types, insights SSE handling, chart helpers"
```

---

### Task 7: Card shell, sparkline, score / trend / IV cards

**Files:**
- Create: `frontend/components/insights/InsightCard.tsx`, `Sparkline.tsx`, `ScoreCard.tsx`, `TrendCard.tsx`, `IvCard.tsx`

**Interfaces:**
- Consumes: types + `@/lib/chart` (Task 6).
- Produces default exports:
  - `InsightCard({ title, source?, className?, children })`
  - `Sparkline({ values, color?, width?, height?, label })`
  - `ScoreCard({ score, trend?, className? })`
  - `TrendCard({ trend, className? })`
  - `IvCard({ iv, trend?, className? })`

- [ ] **Step 1: Create `InsightCard.tsx`**

```tsx
/**
 * InsightCard.tsx — shared frame for insight visuals: title, body, provenance footer.
 * Report text is rendered as JSX text only (T-06-01).
 */
import type { ReactNode } from "react";
import type { InsightSource } from "@/lib/types";

export default function InsightCard({
  title,
  source,
  className = "",
  children,
}: {
  title: string;
  source?: InsightSource;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`min-w-0 rounded-2xl border border-ink-700 bg-ink-900/70 p-4 ${className}`}>
      <h4 className="mb-3 font-mono text-[10px] uppercase tracking-[0.2em] text-paper-dim">{title}</h4>
      {children}
      {source && (
        <p
          className="mt-3 truncate border-t border-ink-700/70 pt-2 font-mono text-[10px] text-paper-mute"
          title={source.source_path}
        >
          From {source.source_path} · {source.generated_date}
        </p>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Create `Sparkline.tsx`**

```tsx
/** Sparkline.tsx — tiny line chart with an end dot; renders nothing under 2 points. */
import { extent, linePath, scale } from "@/lib/chart";

export default function Sparkline({
  values,
  color = "#ffb547",
  width = 120,
  height = 28,
  label,
}: {
  values: (number | null | undefined)[];
  color?: string;
  width?: number;
  height?: number;
  label: string;
}) {
  const nums = values.filter((v): v is number => typeof v === "number");
  if (nums.length < 2) return null;
  const [lo, hi] = extent(nums);
  const x = scale(0, values.length - 1, 2, width - 3);
  const y = scale(lo, hi, height - 3, 3);
  const lastIdx = values.map((v) => typeof v === "number").lastIndexOf(true);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      <path
        d={linePath(values.map((v, i) => [x(i), typeof v === "number" ? y(v) : null]))}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(lastIdx)} cy={y(values[lastIdx] as number)} r="2.5" fill={color} />
    </svg>
  );
}
```

- [ ] **Step 3: Create `ScoreCard.tsx`**

```tsx
/**
 * ScoreCard.tsx — composite trade score gauge (bands = README grade table),
 * dimension bars with weights, price / stop / catalyst, 30-run sparklines.
 */
import type { ScoreInsight, TrendInsight } from "@/lib/types";
import { GRADE_BANDS, band, daysUntil, money, pctFrom, signalColor } from "@/lib/chart";
import InsightCard from "./InsightCard";
import Sparkline from "./Sparkline";

const CX = 100;
const CY = 96;
const R = 80;

/** Point on the gauge arc for a 0–100 score (0 = left, 100 = right). */
function arcPoint(score: number, r = R): [number, number] {
  const t = Math.PI * (1 - Math.min(100, Math.max(0, score)) / 100);
  return [CX + r * Math.cos(t), CY - r * Math.sin(t)];
}

function arc(from: number, to: number): string {
  const [x0, y0] = arcPoint(from);
  const [x1, y1] = arcPoint(to);
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-paper-mute">{label}</dt>
      <dd className="mt-0.5 text-paper">
        {value}
        {sub && <span className="ml-1.5 text-[10px] text-paper-mute">{sub}</span>}
      </dd>
    </div>
  );
}

export default function ScoreCard({
  score,
  trend,
  className,
}: {
  score: ScoreInsight;
  trend?: TrendInsight;
  className?: string;
}) {
  const current = band(score.composite);
  const [nx, ny] = arcPoint(score.composite, R - 18);
  const recent = trend?.points.slice(-30) ?? [];
  const days = score.catalyst_date ? daysUntil(score.catalyst_date) : null;
  const grade = score.grade ?? current.grade;
  const signal = score.signal ?? current.signal;

  return (
    <InsightCard title="Trade score" source={score.source} className={className}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <svg
          viewBox="0 0 200 104"
          className="w-full max-w-[200px] flex-shrink-0"
          role="img"
          aria-label={`Trade score ${score.composite} of 100, grade ${grade}, signal ${signal}`}
        >
          {GRADE_BANDS.map((b, i) => (
            <path
              key={b.grade}
              d={arc(b.min + 0.8, (i === 0 ? 100 : GRADE_BANDS[i - 1].min) - 0.8)}
              stroke={b.color}
              strokeWidth="10"
              fill="none"
              opacity={b === current ? 1 : 0.22}
            />
          ))}
          <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="#ece6d9" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx={CX} cy={CY} r="5" fill="#ece6d9" />
        </svg>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-4xl font-semibold text-paper">{score.composite}</span>
            <span className="font-mono text-sm text-paper-mute">/100</span>
            <span
              className="rounded-md border px-2 py-0.5 font-mono text-xs"
              style={{ color: current.color, borderColor: `${current.color}66` }}
            >
              {grade}
            </span>
            <span
              className="rounded-full px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wider text-ink-950"
              style={{ background: signalColor(signal) }}
            >
              {signal}
            </span>
          </div>
          <ul className="mt-4 space-y-2">
            {score.dimensions.map((d) => (
              <li key={d.name} className="grid grid-cols-[88px_1fr_28px_34px] items-center gap-2 text-xs">
                <span className="text-paper-dim">{d.name}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${Math.min(100, d.score)}%`, background: band(d.score).color }}
                  />
                </span>
                <span className="text-right font-mono tabular-nums text-paper">{d.score}</span>
                <span className="text-right font-mono text-[10px] text-paper-mute">{Math.round(d.weight * 100)}%</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-700/70 pt-3 font-mono text-[11px] sm:grid-cols-4">
        {score.price != null && <Stat label="Price" value={money(score.price)} />}
        {score.stop_loss != null && (
          <Stat
            label="Stop"
            value={money(score.stop_loss)}
            sub={score.price ? pctFrom(score.stop_loss, score.price) : undefined}
          />
        )}
        {days != null && days >= 0 && <Stat label="Catalyst" value={`${days}d`} sub={score.catalyst_date ?? undefined} />}
        {recent.length >= 2 && (
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-paper-mute">Last {recent.length} runs</dt>
            <dd className="mt-1 flex gap-2">
              <Sparkline values={recent.map((p) => p.price)} color="#ece6d9" width={56} height={20} label="Price trend" />
              <Sparkline values={recent.map((p) => p.score)} width={56} height={20} label="Score trend" />
            </dd>
          </div>
        )}
      </dl>
    </InsightCard>
  );
}
```

- [ ] **Step 4: Create `TrendCard.tsx`**

```tsx
"use client";

/**
 * TrendCard.tsx — price / score / IV-rank lines on a shared date axis plus a
 * signal-coloured strip; hovering any row moves a shared readout.
 */
import { useState, type MouseEvent } from "react";
import type { TrendInsight, TrendPoint } from "@/lib/types";
import { extent, linePath, money, scale, signalColor } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 520;
const H = 56;

const SERIES: { key: "price" | "score" | "iv_rank"; label: string; color: string; fmt: (v: number) => string }[] = [
  { key: "price", label: "Price", color: "#ece6d9", fmt: (v) => money(v) },
  { key: "score", label: "Score", color: "#ffb547", fmt: (v) => String(v) },
  { key: "iv_rank", label: "IV rank", color: "#b9a4ff", fmt: (v) => `${v}%` },
];

function readout(p: TrendPoint): string {
  const parts = SERIES.filter((s) => p[s.key] != null).map((s) => `${s.label} ${s.fmt(p[s.key] as number)}`);
  return [p.date, ...parts, p.signal].filter(Boolean).join(" · ");
}

export default function TrendCard({ trend, className }: { trend: TrendInsight; className?: string }) {
  const pts = trend.points;
  const [hover, setHover] = useState<number | null>(null);
  const x = scale(0, pts.length - 1, 0, W);
  const active = hover ?? pts.length - 1;

  function onMove(e: MouseEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1));
    setHover(Math.min(pts.length - 1, Math.max(0, i)));
  }

  return (
    <InsightCard title={`Trend · last ${pts.length} reports`} className={className}>
      <p className="mb-3 min-h-[1rem] font-mono text-[11px] text-paper-dim">{readout(pts[active])}</p>
      {SERIES.map((s) => {
        const vals = pts.map((p) => p[s.key] ?? null);
        const nums = vals.filter((v): v is number => v != null);
        if (nums.length < 2) return null;
        const [lo, hi] = extent(nums);
        const y = scale(lo, hi, H - 4, 4);
        const delta = nums[nums.length - 1] - nums[0];
        const deltaText = s.key === "price" ? `$${Math.abs(delta).toFixed(2)}` : Math.abs(delta).toFixed(0);
        return (
          <div key={s.key} className="mb-2 grid grid-cols-[56px_1fr_64px] items-center gap-3">
            <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">{s.label}</span>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              className="h-14 w-full cursor-crosshair"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              role="img"
              aria-label={`${s.label} from ${s.fmt(nums[0])} to ${s.fmt(nums[nums.length - 1])}`}
            >
              <path
                d={linePath(vals.map((v, i) => [x(i), v == null ? null : y(v)]))}
                fill="none"
                stroke={s.color}
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={x(active)}
                x2={x(active)}
                y1="0"
                y2={H}
                stroke="#6d6a63"
                strokeDasharray="2 3"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <span className={`text-right font-mono text-[11px] ${delta >= 0 ? "text-gain" : "text-loss"}`}>
              {delta >= 0 ? "▲" : "▼"} {deltaText}
            </span>
          </div>
        );
      })}
      <div className="mt-1 grid grid-cols-[56px_1fr_64px] items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">Signal</span>
        <svg
          viewBox={`0 0 ${pts.length} 1`}
          preserveAspectRatio="none"
          className="h-3 w-full cursor-crosshair rounded-sm"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={`Signal from ${pts[0].signal ?? "unknown"} to ${pts[pts.length - 1].signal ?? "unknown"}`}
        >
          {pts.map((p, i) => (
            <rect key={p.date} x={i} y="0" width="1.02" height="1" fill={signalColor(p.signal)} opacity={i === active ? 1 : 0.65} />
          ))}
        </svg>
        <span />
      </div>
    </InsightCard>
  );
}
```

- [ ] **Step 5: Create `IvCard.tsx`**

```tsx
/** IvCard.tsx — IV rank meter (0–100) with IV-rank history sparkline. */
import type { IvInsight, TrendInsight } from "@/lib/types";
import InsightCard from "./InsightCard";
import Sparkline from "./Sparkline";

export default function IvCard({ iv, trend, className }: { iv: IvInsight; trend?: TrendInsight; className?: string }) {
  const history = trend?.points.map((p) => p.iv_rank) ?? [];
  const pos = Math.min(100, Math.max(0, iv.iv_rank));
  return (
    <InsightCard title="Implied volatility" source={iv.source} className={className}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold text-paper">{iv.iv_rank}</span>
        <span className="font-mono text-xs text-paper-mute">IV rank · 52-week</span>
      </div>
      <div
        className="relative mt-3 h-2 rounded-full bg-gradient-to-r from-ink-700 via-[#b9a4ff]/40 to-[#b9a4ff]"
        role="img"
        aria-label={`IV rank ${iv.iv_rank} of 100`}
      >
        <span className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded bg-paper" style={{ left: `${pos}%` }} />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-paper-mute">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      {history.filter((v) => v != null).length >= 2 && (
        <div className="mt-3 flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-paper-mute">History</span>
          <Sparkline values={history} color="#b9a4ff" width={160} height={28} label="IV rank history" />
        </div>
      )}
    </InsightCard>
  );
}
```

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/insights
git commit -m "feat(insights): score, trend and IV cards"
```

---

### Task 8: Options cards, panel, message wiring, visual check

**Files:**
- Create: `frontend/components/insights/ExpectedMoveCard.tsx`, `KeyLevelsCard.tsx`, `PayoffCard.tsx`, `InsightsPanel.tsx`
- Modify: `frontend/components/MessageBubble.tsx`
- Temporary (deleted in Step 8): `frontend/app/design-preview/page.tsx`, `frontend/app/design-preview/payloads.json`

**Interfaces:**
- Consumes: Task 6 types/helpers, Task 7 cards.
- Produces: `InsightsPanel({ insights })` rendered by `MessageBubble` above `QuoteCard`.

- [ ] **Step 1: Create `ExpectedMoveCard.tsx`**

```tsx
/** ExpectedMoveCard.tsx — 1W / 1M / 90D expected-move bands on a price axis. */
import type { ExpectedMoveInsight } from "@/lib/types";
import { extent, money, scale } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 560;
const LEFT = 130;
const RIGHT = 14;
const TOP = 24;
const ROW = 36;

export default function ExpectedMoveCard({ data, className }: { data: ExpectedMoveInsight; className?: string }) {
  const [lo, hi] = extent([...data.ranges.flatMap((r) => [r.low, r.high]), data.price], 0.04);
  const x = scale(lo, hi, LEFT, W - RIGHT);
  const H = TOP + data.ranges.length * ROW + 20;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + (hi - lo) * t);
  const summary =
    `Expected move from ${money(data.price)}: ` +
    data.ranges.map((r) => `${r.label} ${money(r.low)} to ${money(r.high)}`).join("; ");

  return (
    <InsightCard title="Expected move" source={data.source} className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={summary}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 4} y2={H - 18} stroke="#1e2330" />
            <text x={x(t)} y={H - 4} textAnchor="middle" fontSize="11" className="fill-paper-mute font-mono">
              {money(t)}
            </text>
          </g>
        ))}
        {data.ranges.map((r, i) => {
          const y = TOP + i * ROW;
          return (
            <g key={r.label}>
              <text x="0" y={y + 14} fontSize="12" className="fill-paper-dim">{r.label}</text>
              {r.pct != null && (
                <text x="0" y={y + 28} fontSize="11" className="fill-paper-mute font-mono">±{r.pct}%</text>
              )}
              <text x={x(r.low)} y={y + 10} fontSize="11" className="fill-paper-dim font-mono">
                {money(r.low, r.approx)}
              </text>
              <text x={x(r.high)} y={y + 10} textAnchor="end" fontSize="11" className="fill-paper-dim font-mono">
                {money(r.high, r.approx)}
              </text>
              <rect
                x={x(r.low)}
                y={y + 15}
                width={Math.max(2, x(r.high) - x(r.low))}
                height="12"
                rx="4"
                fill="#ffb547"
                opacity={Math.max(0.18, 0.6 - i * 0.14)}
              />
            </g>
          );
        })}
        <line x1={x(data.price)} x2={x(data.price)} y1={TOP - 8} y2={H - 18} stroke="#ffb547" strokeWidth="2" />
        <text x={x(data.price)} y={TOP - 12} textAnchor="middle" fontSize="11" className="fill-amber-glow font-mono">
          now {money(data.price)}
        </text>
      </svg>
    </InsightCard>
  );
}
```

- [ ] **Step 2: Create `KeyLevelsCard.tsx`**

```tsx
/**
 * KeyLevelsCard.tsx — price ladder: resistance above (loss tint), support below
 * (gain tint), current price in amber. Labels are de-collided with leader lines.
 */
import type { KeyLevelsInsight } from "@/lib/types";
import { extent, money, pctFrom, scale } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 330;
const TRACK = 16;
const LABEL = 44;
const GAP = 18;
const PAD = 14;

function short(label: string): string {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

export default function KeyLevelsCard({ data, className }: { data: KeyLevelsInsight; className?: string }) {
  const rows = [
    ...data.levels.map((l) => ({ ...l, now: false })),
    { label: "Now", price: data.price, note: null, approx: false, now: true },
  ].sort((a, b) => b.price - a.price);
  const [lo, hi] = extent(rows.map((r) => r.price), 0.04);
  const base = Math.max(220, rows.length * GAP + 2 * PAD);
  const y = scale(hi, lo, PAD, base - PAD);
  let prev = -Infinity;
  const placed = rows.map((r) => {
    const ly = Math.max(y(r.price), prev + GAP);
    prev = ly;
    return { ...r, ty: y(r.price), ly };
  });
  const H = Math.max(base, prev + PAD);
  const summary = `Key levels around ${money(data.price)}: ` + data.levels.map((l) => `${l.label} ${money(l.price)}`).join("; ");

  return (
    <InsightCard title="Key levels" source={data.source} className={className}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={summary}>
        <line x1={TRACK} x2={TRACK} y1={PAD} y2={base - PAD} stroke="#2a3142" strokeWidth="2" />
        {placed.map((r) => {
          const color = r.now ? "#ffb547" : r.price > data.price ? "#ff5c6c" : "#3ddc97";
          return (
            <g key={`${r.label}-${r.price}`}>
              <title>{r.note ?? r.label}</title>
              <line x1={TRACK - 6} x2={TRACK + 6} y1={r.ty} y2={r.ty} stroke={color} strokeWidth={r.now ? 3 : 2} />
              <path d={`M${TRACK + 6},${r.ty} L${LABEL - 6},${r.ly}`} stroke={color} strokeOpacity="0.4" fill="none" />
              <text x={LABEL} y={r.ly + 4} fontSize="12" className="font-mono" fill={color}>
                {money(r.price, r.approx)}
              </text>
              <text x={LABEL + 70} y={r.ly + 4} fontSize="12" className={r.now ? "fill-amber-glow" : "fill-paper-dim"}>
                {short(r.label)}
              </text>
              {!r.now && (
                <text x={W} y={r.ly + 4} textAnchor="end" fontSize="11" className="fill-paper-mute font-mono">
                  {pctFrom(r.price, data.price)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </InsightCard>
  );
}
```

- [ ] **Step 3: Create `PayoffCard.tsx`**

```tsx
/**
 * PayoffCard.tsx — at-expiry P/L curve for the recommended strategy, computed by the
 * backend from the report's legs. Gain area green, loss area red, strikes dashed.
 */
import { useId } from "react";
import type { StrategyInsight } from "@/lib/types";
import { extent, linePath, money, scale, signedMoney } from "@/lib/chart";
import InsightCard from "./InsightCard";

const W = 560;
const H = 220;
const L = 46;
const R = 12;
const T = 16;
const B = 26;

export default function PayoffCard({ data, className }: { data: StrategyInsight; className?: string }) {
  const clip = useId().replace(/:/g, "");
  const xs = data.curve.map((c) => c[0]);
  const ys = data.curve.map((c) => c[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const [y0, y1] = extent([...ys, 0], 0.15);
  const x = scale(x0, x1, L, W - R);
  const y = scale(y0, y1, H - B, T);
  const line = linePath(data.curve.map(([a, b]) => [x(a), y(b)]));
  const zero = y(0);
  const area = `${line}L${x(x1).toFixed(1)},${zero.toFixed(1)}L${x(x0).toFixed(1)},${zero.toFixed(1)}Z`;
  const strikes = Array.from(new Set(data.legs.map((l) => l.strike)));
  const maxGain = data.max_gain == null ? "Unlimited" : signedMoney(data.max_gain);
  const maxLoss = data.max_loss == null ? "Unlimited" : signedMoney(data.max_loss);
  const summary =
    `${data.name} payoff at expiration: max loss ${maxLoss}, max gain ${maxGain}` +
    (data.breakevens.length ? `, breakeven ${data.breakevens.map((b) => money(b)).join(" and ")}` : "");

  return (
    <InsightCard title={`${data.name} · payoff at ${data.expiration}`} source={data.source} className={className}>
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-paper-mute">
        <span>
          Max gain <span className="text-gain">{maxGain}</span>
        </span>
        <span>
          Max loss <span className="text-loss">{maxLoss}</span>
        </span>
        {data.breakevens.map((b) => (
          <span key={b}>
            Breakeven <span className="text-paper">{money(b)}</span>
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={summary}>
        <defs>
          <clipPath id={`${clip}-up`}>
            <rect x="0" y="0" width={W} height={zero} />
          </clipPath>
          <clipPath id={`${clip}-down`}>
            <rect x="0" y={zero} width={W} height={H - zero} />
          </clipPath>
        </defs>
        <path d={area} fill="#3ddc97" opacity="0.18" clipPath={`url(#${clip}-up)`} />
        <path d={area} fill="#ff5c6c" opacity="0.18" clipPath={`url(#${clip}-down)`} />
        <line x1={L} x2={W - R} y1={zero} y2={zero} stroke="#6d6a63" />
        <text x={L - 6} y={zero + 4} textAnchor="end" fontSize="11" className="fill-paper-mute font-mono">$0</text>
        {strikes.map((k) => (
          <g key={k}>
            <line x1={x(k)} x2={x(k)} y1={T} y2={H - B} stroke="#2a3142" strokeDasharray="3 4" />
            <text x={x(k)} y={H - 8} textAnchor="middle" fontSize="11" className="fill-paper-dim font-mono">
              {money(k)}
            </text>
          </g>
        ))}
        <path d={line} fill="none" stroke="#ece6d9" strokeWidth="2" strokeLinejoin="round" />
        {data.breakevens.map((b) => (
          <circle key={b} cx={x(b)} cy={zero} r="4" fill="#ffb547" />
        ))}
        <line x1={x(data.price)} x2={x(data.price)} y1={T} y2={H - B} stroke="#ffb547" strokeOpacity="0.7" />
        <text x={x(data.price) + 4} y={T + 10} fontSize="11" className="fill-amber-glow font-mono">
          now {money(data.price)}
        </text>
      </svg>
      <table className="mt-3 w-full font-mono text-[11px]">
        <tbody>
          {data.includes_stock && (
            <tr className="border-t border-ink-700">
              <td className="py-1.5 text-gain">Long</td>
              <td className="text-paper">Stock</td>
              <td className="text-paper-dim">{money(data.price)}</td>
              <td className="text-paper-mute">cost basis</td>
            </tr>
          )}
          {data.legs.map((l, i) => (
            <tr key={i} className="border-t border-ink-700">
              <td className={`py-1.5 ${l.action === "buy" ? "text-gain" : "text-loss"}`}>{l.action === "buy" ? "Buy" : "Sell"}</td>
              <td className="text-paper">
                {money(l.strike)} {l.type === "call" ? "Call" : "Put"}
              </td>
              <td className="text-paper-dim">{money(l.premium, l.approx)}</td>
              <td className="text-paper-mute">{data.expiration}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-paper-mute">
        Per share at expiration · premiums as quoted in report · ignores fees and early assignment
      </p>
    </InsightCard>
  );
}
```

- [ ] **Step 4: Create `InsightsPanel.tsx`**

```tsx
/**
 * InsightsPanel.tsx — lays out whichever insight sections the backend sent.
 * Missing sections render nothing; full-width cards span both columns.
 */
import type { Insights } from "@/lib/types";
import ExpectedMoveCard from "./ExpectedMoveCard";
import IvCard from "./IvCard";
import KeyLevelsCard from "./KeyLevelsCard";
import PayoffCard from "./PayoffCard";
import ScoreCard from "./ScoreCard";
import TrendCard from "./TrendCard";

export default function InsightsPanel({ insights }: { insights: Insights }) {
  const { score, trend, iv, expected_move, key_levels, strategy } = insights;
  const pair = key_levels && iv;
  return (
    <div className="animate-rise mb-5 grid gap-3 sm:grid-cols-2">
      {score && <ScoreCard score={score} trend={trend} className="sm:col-span-2" />}
      {trend?.focus && <TrendCard trend={trend} className="sm:col-span-2" />}
      {expected_move && <ExpectedMoveCard data={expected_move} className="sm:col-span-2" />}
      {strategy && <PayoffCard data={strategy} className="sm:col-span-2" />}
      {key_levels && <KeyLevelsCard data={key_levels} className={pair ? "" : "sm:col-span-2"} />}
      {iv && <IvCard iv={iv} trend={trend} className={pair ? "" : "sm:col-span-2"} />}
    </div>
  );
}
```

- [ ] **Step 5: Wire into `MessageBubble.tsx`**

Add the import below `import QuoteCard from "./QuoteCard";`:

```tsx
import InsightsPanel from "./insights/InsightsPanel";
```

Replace:

```tsx
      {/* Live quote card — shown above the text body (02-02) */}
      {message.quote && <QuoteCard quote={message.quote} />}
```

with:

```tsx
      {/* Grounded report visuals — every number from report data, never the LLM */}
      {message.insights && <InsightsPanel insights={message.insights} />}

      {/* Live quote card — shown above the text body (02-02) */}
      {message.quote && <QuoteCard quote={message.quote} />}
```

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc exits 0; vitest passes.

- [ ] **Step 6: Generate real payloads for the visual check**

Run from `backend/`:

```bash
.venv/bin/python - <<'EOF' > ../frontend/app/design-preview/payloads.json
import json, logging
logging.disable(logging.WARNING)
from src.insights import build_insights
cases = [
    ("MARA options", "MARA", {"OPTIONS"}, "factual"),
    ("MARA overview", "MARA", {"ANALYSIS", "OPTIONS"}, "factual"),
    ("MARA trend", "MARA", set(), "trajectory"),
    ("NIO options", "NIO", {"OPTIONS"}, "factual"),
    ("CLOV options (PMCC)", "CLOV", {"OPTIONS"}, "factual"),
]
print(json.dumps([{"title": t, "insights": build_insights(tk, ctx, it)} for t, tk, ctx, it in cases]))
EOF
```

(Create the directory first: `mkdir -p frontend/app/design-preview`.)

Create `frontend/app/design-preview/page.tsx` (temporary):

```tsx
"use client";
// TEMPORARY visual check for insights — delete before commit.
import InsightsPanel from "@/components/insights/InsightsPanel";
import type { Insights } from "@/lib/types";
import payloads from "./payloads.json";

export default function Preview() {
  return (
    <main className="desk-backdrop min-h-dvh">
      <div className="mx-auto max-w-3xl space-y-10 px-6 py-10">
        {(payloads as { title: string; insights: Insights | null }[]).map((p) => (
          <section key={p.title}>
            <h2 className="mb-3 font-display text-2xl">{p.title}</h2>
            {p.insights ? <InsightsPanel insights={p.insights} /> : <p className="text-paper-mute">no insights</p>}
          </section>
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Look at it**

With the dev server running (`cd frontend && npm run dev`, or the existing one on :3001), open `http://localhost:3001/design-preview` in the browser at 1440×900 and at 375×812. Check:
- MARA options: expected-move bands with `now $11.23`, collar payoff with max loss −$1.43 / max gain +$1.57 / breakeven $11.43, key-levels ladder, IV 32.
- MARA overview: score 29 / D / CAUTION, dimension bars 28 / 27 / 32 / 27 / 33.
- MARA trend: three lines + signal strip; hover moves the readout.
- CLOV: no payoff card (PMCC), other options cards present.
- No console errors (hydration or otherwise); nothing overflows horizontally at 375 px.

Fix any visual defect in the owning component before continuing.

- [ ] **Step 8: Remove the preview and commit**

```bash
rm -r frontend/app/design-preview
cd frontend && npx tsc --noEmit && cd ..
git add frontend/components/insights frontend/components/MessageBubble.tsx
git commit -m "feat(insights): expected-move, key-levels and payoff cards in answers"
```

---

### Task 9: Live verification against success criteria

**Files:** none modified (verification only).

**Interfaces:**
- Consumes: everything above, live Pinecone (read key in `backend/.env`).

- [ ] **Step 1: Check spec §10 criteria 1–4 against the live index**

Run from `backend/`:

```bash
.venv/bin/python - <<'EOF'
import logging, time
logging.disable(logging.WARNING)
from src.insights import build_insights

t = time.perf_counter(); o = build_insights("MARA", {"OPTIONS"}, "factual"); cold = time.perf_counter() - t
t = time.perf_counter(); build_insights("MARA", {"OPTIONS"}, "factual"); warm = time.perf_counter() - t
s = o["strategy"]
print("1. options:", sorted(o), s["name"], s["max_loss"], s["max_gain"], s["breakevens"], o["strategy"]["source"])
a = build_insights("MARA", {"ANALYSIS"}, "factual")["score"]
print("2. score:", a["composite"], a["grade"], a["signal"], [d["score"] for d in a["dimensions"]])
tr = build_insights("MARA", set(), "trajectory")["trend"]
print("3. trend:", tr["focus"], len(tr["points"]), tr["points"][-1])
print("4. VDY:", build_insights("VDY", {"OPTIONS"}, "factual"))
print(f"build time cold {cold:.2f}s warm {warm:.2f}s (off the token path)")
EOF
```

Expected (values as of the 2026-10-03 reports; later reports change the numbers but not the shape):
- `1.` keys include `expected_move, iv, key_levels, strategy, trend`; `Collar -1.43 1.57 [11.43]`; source `TRADE-OPTIONS-MARA-20261003-1311.md`.
- `2.` `29 D CAUTION [28, 27, 32, 27, 33]`.
- `3.` `True`, ≥ 2 points, last point dated today.
- `4.` `None` (or a dict without options sections) and no exception.

- [ ] **Step 2: Confirm criterion 5 (no LLM-derived values) by inspection**

Run: `cd backend && grep -n "complete\|llm\|stream_complete\|full_response" src/insights.py`
Expected: no matches — `insights.py` never touches LLM output.

- [ ] **Step 3: Confirm criterion 6 (time-to-first-token) by construction + tests**

`build_insights` runs in `_INSIGHTS_POOL`; the token loop only calls the non-blocking `future.done()`. `test_stream_waits_briefly_for_slow_insights` and `test_stream_drops_insights_past_the_wait_budget` (Task 5) pin that a slow or failing builder never delays tokens or `done`. Record the cold/warm build times from Step 1 in the PR description.

- [ ] **Step 4: Full suites**

Run: `cd backend && .venv/bin/python -m pytest -q` then `cd ../frontend && npx vitest run && npx tsc --noEmit`
Expected: all green.

- [ ] **Step 5: Hand the live UI check to the user**

The built-in browser can't log in, so ask the user to try, in their logged-in session at `http://localhost:3001`:
1. `recent options report on MARA` → expected move, payoff, key levels, IV.
2. `tell me about MARA` → score card (+ options cards if options chunks were retrieved).
3. `how has MARA's score trended?` → trend card.
4. `options on VDY` → answer with no options cards, no errors.
