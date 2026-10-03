# Report Insights — grounded visuals in chat answers

**Status:** Draft for review · **Date:** 2026-10-03 · **Scope:** `backend/` + `frontend/`

## 1. Goal

When an answer draws on stored reports (options, analysis), show the key numbers as
human-readable visuals — gauges, ranges, ladders, payoff and trend charts — inline in
the answer, above the written memo.

**Grounding guarantee (hard requirement):** every value in a visual comes from the
reports — Pinecone record metadata or tables parsed from the stored report text — or is
computed deterministically by code from those values. **No chart value is produced or
transcribed by the LLM.** The written answer remains LLM-generated (grounded via RAG +
citations); the visuals are the authoritative numbers beside it.

Values the reports quote approximately (`~90%`, `~$1.55`) keep an `approx` flag and are
rendered with `~`. Every card shows its provenance (`source_path · generated_date`).

## 2. Decisions (agreed in brainstorming)

| Decision | Choice |
|---|---|
| Visual set | Score breakdown, trend history, options visuals (expected move, key levels, IV), strategy payoff |
| Placement | Inline per answer, only the visuals relevant to what the answer is grounded in |
| Data source | **Approach A** — backend builds an `insights` payload from report data; LLM never emits chart data |
| Rendering | Hand-built SVG components in the Night Desk style; no chart library |

Rejected: LLM-emitted chart blocks (fabrication risk, malformed partial JSON) and
frontend charting of tables found in LLM output (generic; model-transcribed numbers).

## 3. Data available (verified against the live index, 2026-10-03)

- **ANALYSIS metadata:** `composite_score`, `technical_score`, `fundamental_score`,
  `sentiment_score`, `risk_score`, `thesis_score`, `grade`, `signal`,
  `price_at_analysis`, `stop_loss`, `nearest_catalyst_date`, `generated_date`.
- **OPTIONS metadata:** `iv_rank` (absent for tickers without liquid options),
  `price_at_analysis`, `signal`, `recommended_strategy`, `strategy_outlook`.
- **History:** ~115 daily runs per ticker per type → time series of the above.
  Some legacy runs carry the undated ID timestamp `00000000-0000`; these are excluded.
- **OPTIONS report tables** (stable across tickers and dates):
  - Expected Move: `| Timeframe | Expected Move ($) | Expected Move (%) | Range |`
  - Key Levels: `| Level | Price | Significance |` (absent in some older runs)
  - Strategy legs: `| Leg | Action | Strike | Expiration|Expiry | Type | Price|Est. Price|Price (est.) |`
- Sections can be split across chunks (e.g. `recommended-strategies:4` / `:5`), so
  parsing runs over the full report text re-assembled in `chunk_index` order.

## 4. Architecture & data flow

```
/chat/stream
  retrieve (top-6 chunks, newest report per type)        ── existing
  emit citations, quote                                   ── existing
  submit build_insights(...) to a thread pool  ──┐        ── new, concurrent
  stream LLM tokens; between tokens, if ready ───┴─► emit `insights` (once)
  after stream: wait ≤ 2 s for insights, else drop + log
  persist turns; emit done                                ── existing
```

### 4.1 `backend/src/pinecone_client.py` (additions)

- Widen the per-ticker ID cache: `_run_index(ticker) -> {report_type: {run_key: [chunk_ids]}}`
  (same 10-min TTL bucket as today). `_latest_dates()` is derived from it, so retrieval
  keeps a single listing per ticker.
- `latest_run_chunks(ticker, report_type) -> list[dict]` — all chunks of the newest dated
  run for that type, normalized, ordered by `chunk_index` (one `fetch`).
- `run_metadata(ticker, report_type, limit=60) -> list[dict]` — metadata of the first
  chunk of each of the newest `limit` dated runs, oldest → newest. Fetched in batches of
  ≤ 100 IDs; cached per ticker with the same TTL.

### 4.2 `backend/src/insights.py` (new, pure functions)

- `build_insights(ticker, context_types, intent) -> dict | None` — orchestrates the
  sections below; each section is built inside its own `try/except` and omitted on any
  failure (logged as a warning). Returns `None` when no section was built.
- `parse_expected_move(text) -> dict | None`
- `parse_key_levels(text) -> dict | None`
- `parse_strategy(text, price) -> dict | None` — the first legs table inside the
  `### Strategy 1: <name>` section; name from that heading. No heading → `None` (legs
  can't be attributed to the recommended strategy).
- `payoff(legs, price, includes_stock) -> dict | None` (see §5).
- `score_card(meta) -> dict | None`, `trend(points) -> dict | None`.

Parser rules: locate tables by header names (case-insensitive, column order not
assumed); strip `$`, `%`, `+/-`, `~`, commas; record `approx=True` when a cell had `~`;
reject a row whose required cells aren't numeric; reject a table with no valid rows;
for ranges (`$8.88 — $13.58`, any dash) require `low < high`. Labels are plain strings
truncated to 48 chars. A key level outside 0.1×–10× the current price is dropped.

### 4.3 Relevance rules

`context_types` = report types of the chunks the answer is grounded in (the retrieved
chunks). No ticker → no insights.

| Condition | Sections |
|---|---|
| `ANALYSIS` in context | `score` (+ `trend` points for sparklines) |
| `OPTIONS` in context | `expected_move`, `key_levels`, `strategy`, `iv` (+ `trend` points) |
| `intent == "trajectory"` | `trend` (full card), plus the above as applicable |

### 4.4 SSE contract (additive)

New optional event `insights`, `data` = JSON payload (§6). Emitted at most once,
anywhere between `citations` and `done`. Clients that don't know it ignore it (today's
frontend already ignores unknown events). Non-streaming `/chat` is unchanged.

### 4.5 Concurrency

`chat.py` holds a module-level `ThreadPoolExecutor(max_workers=4)`. The future is
checked (`done()`) after each token; on completion its result is emitted immediately.
After the token loop: `result(timeout=2.0)`; on timeout or exception → log, no event.

## 5. Payoff math

Per share, at expiration, single expiration only.

- Legs: `{action: buy|sell, type: call|put, strike, premium, approx}`, 1 unit each.
- Stock leg included when the strategy name matches *collar*, *covered call* or
  *protective put* (case-insensitive); cost basis = `price_at_analysis`.
- `P/L(S) = stock·(S − P0) + Σ sign·(intrinsic(S) − premium)`, `sign = +1` buy / `−1`
  sell, `intrinsic_call = max(S − K, 0)`, `intrinsic_put = max(K − S, 0)`.
- Curve over `S ∈ [0.6·min(strikes, P0), 1.4·max(strikes, P0)]`: 60 evenly spaced points
  plus the strike kinks.
- Max gain / max loss: P/L is piecewise linear, so evaluate at `S = 0`, every strike and
  the upper range end. Above the highest strike the slope is constant: if it is `> 0`,
  `max_gain = null` (unbounded); if `< 0`, `max_loss = null` (unbounded, e.g. naked call).
- Breakevens: zero crossings, linearly interpolated between kink points.
- Skipped (no `strategy` section) when: no option legs parse, legs have different
  expirations (e.g. PMCC), or any strike/premium is non-numeric.
- Reference check (MARA collar, 2026-10-03): P0 = 11.23, buy 10 P @ 1.55, sell 13 C @
  1.35 → max loss −1.43, max gain +1.57, breakeven 11.43.

## 6. Payload schema

All sections optional. Each section carries `source: {source_path, generated_date}`.

```jsonc
{
  "ticker": "MARA",
  "score": {
    "composite": 29, "grade": "D", "signal": "CAUTION",
    "dimensions": [{"name": "Technical", "score": 28, "weight": 0.25}, /* … 5 total */],
    "price": 11.23, "stop_loss": 9.8, "catalyst_date": "2026-11-05", "source": {…}
  },
  "trend": {
    "points": [{"date": "2026-09-01", "price": 14.1, "score": 35, "iv_rank": 41, "signal": "NEUTRAL"}],
    "focus": false   // true for trajectory questions → full TrendCard; else sparklines only
  },
  "iv": {"iv_rank": 32, "source": {…}},
  "expected_move": {
    "price": 11.23,
    "ranges": [{"label": "Next Week", "low": 8.88, "high": 13.58, "pct": 20.9, "approx": false}],
    "source": {…}
  },
  "key_levels": {
    "price": 11.23,
    "levels": [{"label": "Max Pain (Oct)", "price": 10.0, "note": "Options market equilibrium", "approx": false}],
    "source": {…}
  },
  "strategy": {
    "name": "Collar", "expiration": "Nov 21, 2026", "includes_stock": true, "price": 11.23,
    "legs": [{"action": "buy", "type": "put", "strike": 10.0, "premium": 1.55, "approx": true}],
    "curve": [[6.0, -1.43], /* … */], "breakevens": [11.43],
    "max_gain": 1.57, "max_loss": -1.43, "source": {…}
  }
}
```

`trend.points` (≤ 60, oldest → newest) merges ANALYSIS (price, score, signal) and
OPTIONS (`iv_rank`) by date; ANALYSIS price wins when both exist; one run per date
(the latest that day).

## 7. Frontend

- `lib/types.ts`: `Insights` interfaces mirroring §6; `Message.insights?: Insights`;
  `StreamEvent` doc lists `insights`.
- `ChatWindow.tsx`: handle `insights` → attach to the current assistant message
  (malformed JSON ignored, same as `quote`).
- `MessageBubble.tsx`: render `<InsightsPanel>` below the memo header, above
  `QuoteCard` and the text. Entrance uses the existing `animate-rise`.
- `components/insights/`:
  - `InsightsPanel.tsx` — responsive grid; score, trend, expected move and payoff full
    width; Key levels + IV side by side on ≥ sm.
  - `ScoreCard.tsx` — semicircle gauge banded by the grade table (85+ A+ … 0–24 F),
    needle at composite, grade + signal pills, 5 dimension bars with weights, footer
    (price, stop-loss distance %, catalyst countdown), price/score sparklines (last 30).
  - `TrendCard.tsx` — stacked price / score / IV-rank lines on a shared date axis,
    signal-coloured strip, hover readout, first→last deltas.
  - `ExpectedMoveCard.tsx` — horizontal price axis, nested 1W/1M/90D bands with low/high
    and ±%, current-price marker.
  - `KeyLevelsCard.tsx` — vertical ladder, resistance above / support below, % distance,
    current-price marker.
  - `PayoffCard.tsx` — P/L curve filled gain/loss, dashed strikes, breakeven / max
    gain / max loss labels, current-price marker, legs table, caption *"Per share at
    expiration · premiums as quoted in report · ignores fees and early assignment"*.
  - `IvCard.tsx` — IV-rank meter (0–100) + IV-rank sparkline.
  - `Sparkline.tsx`, `InsightCard.tsx` (shared frame + provenance footer).
- `lib/chart.ts` — pure scale / path / colour / format helpers (under `lib/` so the
  existing vitest config covers them).
- Every chart: `role="img"` with a text summary `aria-label`; all text rendered via JSX
  (no HTML injection, T-06-01); `~` prefix for `approx` values; provenance footer.
- A missing section renders nothing; an answer without insights looks as today.

## 8. Failure handling

- A section failure omits that section only; a builder failure sends no event. Insights
  never produce an `error` event and never block tokens or `done`.
- Pinecone fetch/list errors inside the builder are caught and logged.
- Payload size bounded (≤ 60 trend points, ≤ 12 levels, ≤ 4 legs, ≤ 80 curve points).

## 9. Testing

Backend (pytest, fixtures copied from real report text):
- Parsers: MARA collar (`Price`), MARA bear put spread (`Expiry`), older NIO covered call
  (`Est. Price`), VDY (no tables → `None`), malformed rows rejected, `~` → `approx`.
- Payoff: collar reference values (§5), covered call, bear put spread (no stock), mixed
  expirations → `None`.
- Relevance: ANALYSIS-only → `score`; OPTIONS → options sections; `trajectory` → `trend`;
  no ticker → `None`.
- Route: `insights` emitted between `citations` and `done`; builder exception → tokens +
  `done` still stream, no `insights`; nothing parseable → no event.

Frontend: vitest for `chart.ts` helpers (scales, ticks, signal colours). Visual check in
the browser at desktop + mobile widths via a temporary preview route fed real MARA /
NIO / CLOV payloads (deleted after). Live end-to-end by the user (logged-in session).

## 10. Success criteria

1. "recent options report on MARA" shows expected move, key levels, IV and a collar
   payoff (max loss −1.43, max gain +1.57, breakeven 11.43) matching
   `TRADE-OPTIONS-MARA-20261003-1311`.
2. "tell me about MARA" shows a score card 29 / D / CAUTION with dimensions
   28 / 27 / 32 / 27 / 33.
3. "how has MARA's score trended?" shows the trend card with signal strip.
4. An options question on a ticker without liquid options (e.g. VDY) shows no options
   cards and no errors.
5. Code review confirms no insights value is derived from LLM output.
6. Insights add ≤ ~100 ms to time-to-first-token (measured); failures never break chat.

## 11. Out of scope (follow-ups)

- Persisting insights so restored sessions show visuals (needs a DB column on turns).
- Insights on non-streaming `/chat`.
- Charts for report types not yet in the index (TECHNICAL, FUNDAMENTAL, …).
- Multi-expiration payoff (PMCC, calendars) — needs option pricing, not just intrinsic value.
