# Schema Contract — Producer/Consumer Read-Only Agreement

> **Status:** Locked. This document mirrors the upstream contract declared in
> `ai-trading-claude/README.md` → "Consumer Integration" and codified in
> `ai-trading-claude/scripts/trade_schemas.py`. It is a **read-only** contract for this chatbot.
> Do not redefine it here — consume it as-is.

---

## Index location

| Parameter | Value | Override |
|-----------|-------|---------|
| Index name | `trade-reports` | `PINECONE_INDEX` env var |
| Cloud / region | `aws/us-east-1` | env-overridable if index is migrated |
| Embedding model | `llama-text-embed-v2` | integrated inference — producer-managed, consumer does not embed |
| Namespace | `trade` | `PINECONE_NAMESPACE` env var |

---

## ID scheme (part of the public contract — lexically sortable by recency)

```
<TICKER>:<TYPE>:<YYYYMMDD-HHMM>:<section-slug>:<chunk-index>
```

| Segment | Format | Example |
|---------|--------|---------|
| `<TICKER>` | UPPERCASE; pattern `^[A-Z0-9.\-]+$` | `AAPL` |
| `<TYPE>` | One of the `report_type` enum values (see table below) | `ANALYSIS` |
| `<YYYYMMDD-HHMM>` | UTC timestamp; **lexically sortable** — newest sorts last | `20260530-1430` |
| `<section-slug>` | Kebab-cased report section heading | `executive-summary` |
| `<chunk-index>` | 0-indexed chunk within section | `0` |

Example: `AAPL:ANALYSIS:20260530-1430:executive-summary:0`

The colon-separated structure lets the consumer slice the namespace lexically — `list` with
prefix `AAPL:THESIS:20260530-` returns the chunks of one specific thesis report without a
full namespace scan.

**Retrieval gotcha (inherited from producer experience):** Pinecone metadata `$eq`/`$in`
filters are unreliable on this index. Prefer ID-prefix `list`/`fetch` for `latest` and
`timeline` queries. Treat semantic `retrieve` filters as best-effort only.

---

## Metadata field table

Single source of truth: `ai-trading-claude/scripts/trade_schemas.py` → `RecordMetadata`.
Reproduced here for offline reference and schema-regression testing.

| Field | Type | Always present? | Notes |
|-------|------|-----------------|-------|
| `schema_version` | int | yes | Currently `1`. Increments on breaking changes only (field rename, type change, enum-value removal). Additive changes do NOT bump it. **Consumer MUST validate on read and refuse unknown majors.** |
| `ticker` | string | yes | UPPERCASE; pattern `^[A-Z0-9.\-]+$` |
| `company` | string | yes | Plain company name (mixed case OK) |
| `report_type` | enum string | yes | `ANALYSIS` / `THESIS` / `TECHNICAL` / `FUNDAMENTAL` / `SENTIMENT` / `RISK` / `EARNINGS` / `QUICK` / `OPTIONS` |
| `generated_at` | string (ISO-8601) | yes | Full timestamp with tz offset; e.g. `2026-05-30T14:30:00+00:00` |
| `generated_date` | string (YYYY-MM-DD) | yes | Derived from `generated_at`; use for date-bucket queries |
| `composite_score` | int (0–100) | ANALYSIS only | null on QUICK / single-dimension reports |
| `technical_score` | int (0–100) | ANALYSIS, TECHNICAL | null otherwise |
| `fundamental_score` | int (0–100) | ANALYSIS, FUNDAMENTAL | null otherwise |
| `sentiment_score` | int (0–100) | ANALYSIS, SENTIMENT | null otherwise |
| `risk_score` | int (0–100) | ANALYSIS, RISK | **INVERTED — higher = safer.** A `risk_score` of 80 means LOW risk. Composes correctly into the weighted total when treated this way. Do NOT interpret higher as more risk. |
| `thesis_score` | int (0–100) | ANALYSIS, THESIS | null otherwise |
| `iv_rank` | int (0–100) | OPTIONS | Implied-vol rank. Additive field (no `schema_version` bump). |
| `strategy_outlook` | enum string | OPTIONS | `BULLISH` / `BEARISH` / `NEUTRAL` / `INCOME` / `HEDGE`. Additive. |
| `recommended_strategy` | string | OPTIONS | Primary strategy name (free text, e.g. `Covered Call`). Additive. |
| `position_bias` | enum string | OPTIONS | `LONG` / `FLAT` — holder's existing stock position that conditioned the strategy. Additive. |
| `signal` | enum string | when computed | `STRONG BUY` / `BUY` / `HOLD` / `NEUTRAL` / `CAUTION` / `AVOID` — UPPERCASE, exactly 6 values |
| `grade` | enum string | when computed | `A+` / `A` / `B` / `C` / `D` / `F` — single-letter only, exactly 6 values (no `B+`/`C+`/`C-`/`D+`) |
| `price_at_analysis` | float | when computed | USD |
| `price_target` | float | when computed | USD |
| `stop_loss` | float | when computed | USD |
| `catalysts` | string (comma-joined) | when applicable | Pinecone metadata is flat scalars; lists are comma-joined to a string: `"Earnings, Fed meeting"` |
| `nearest_catalyst_date` | string (YYYY-MM-DD) | when applicable | null otherwise |
| `run_id` | string | when emitted by routine | Format `routine-<YYYYMMDD-HHMM>-<6hex>`. Null on manual `/trade analyze` invocations. Groups all records from one routine sweep — required for "what changed in last run" queries. |
| `source_path` | string | yes | Original filename for citation rendering (e.g. `TRADE-ANALYSIS-AAPL.md`) |
| `section` | string | yes | Original Markdown heading (slugified into the ID; preserved here for display) |
| `chunk_index` | int | yes | 0-indexed chunk within section |

> **Flat-scalar note:** Pinecone metadata is flat scalars only — no nested objects or native
> lists. All list-valued fields (e.g. `catalysts`) are comma-joined into strings at write time
> by the producer. Signals and grades are stored UPPERCASE.

---

## Score → grade → signal mapping (6-band)

| Score | Grade | Signal |
|-------|-------|--------|
| 85–100 | `A+` | `STRONG BUY` |
| 70–84 | `A` | `BUY` |
| 55–69 | `B` | `HOLD` |
| 40–54 | `C` | `NEUTRAL` |
| 25–39 | `D` | `CAUTION` |
| 0–24 | `F` | `AVOID` |

---

## Dimension scoring weights

Used in `composite_score` computation by the producer. For reference only:

| Dimension | Weight | Score field |
|-----------|--------|-------------|
| Technical | 25% | `technical_score` |
| Fundamental | 25% | `fundamental_score` |
| Sentiment | 20% | `sentiment_score` |
| Risk | 15% | `risk_score` (INVERTED) |
| Thesis | 15% | `thesis_score` |

---

## Obtaining a read-only API key

1. Sign in to https://app.pinecone.io.
2. Open your project → **API keys** in the sidebar.
3. Click **+ Create API key**, name it `trading-chatbot-reader`, and select the **Reader** role.
4. Copy the key (shown once only). Paste it into your `.env` file as `PINECONE_READ_KEY`.
5. Never commit the `.env` file — it is gitignored.

Reader-role keys can `query`, `fetch`, and `list` but cannot `upsert` or `delete`.

---

## Stability commitment

| Action | Effect on `schema_version` |
|--------|---------------------------|
| Add a new optional field | No bump — additive, safe |
| Add a new enum value | No bump — additive, safe |
| Rename a field | Bump required — breaking |
| Remove a field | Bump required — breaking |
| Change a field's type | Bump required — breaking |
| Remove an enum value | Bump required — breaking |

**Consumer obligation:** validate `schema_version` on every read. If `schema_version` does
not equal `1` (the current major), raise an error and refuse to process the record. Do not
silently pass records with unknown majors through to the UI.

---

## Namespace conventions

| Namespace | Owner | Purpose |
|-----------|-------|---------|
| `trade` | ai-trading-claude (producer) | All trade report records (read-only for this chatbot) |
| Consumer-owned | trading-chatbot (this repo) | Conversation history, user preferences — registered in `proxy/_lib/validate.py` |

---

*This document is derived from `ai-trading-claude/README.md` → "Consumer Integration" and
`ai-trading-claude/scripts/trade_schemas.py`. Any discrepancy between this file and those
sources means those sources are correct — update this file to match.*
