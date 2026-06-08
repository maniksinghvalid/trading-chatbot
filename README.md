# trading-chatbot

A standalone web chatbot that answers natural-language questions about tickers in your
portfolio using cited, memory-grounded answers retrieved from the `trade-reports` Pinecone
index. Educational and research purposes only — not financial advice.

## What this is

This repository is a **read-only consumer** of the `trade-reports` Pinecone index produced
by [`ai-trading-claude`](https://github.com/zubair-trabzada/ai-trading-claude). It never
writes to Pinecone. Data flows one way: the producer writes analysis reports; this chatbot
reads them and answers questions over them.

```
ai-trading-claude (producer)
  └─ /trade analyze → Pinecone index: trade-reports / namespace: trade
                                           │
                    trading-chatbot (consumer, this repo)
                      └─ FastAPI backend ─►─ read-only Pinecone query
                             │
                         OpenAI RAG
                             │
                       Next.js frontend (browser)
```

## Stack

- **Backend:** Python 3.12, FastAPI, `pinecone>=5`, `openai>=1.0`, SQLite (→ Postgres in Phase 2)
- **Frontend:** Next.js 14 App Router, TypeScript, Tailwind, SSE streaming
- **Schema contract:** `docs/schema-contract.md` — the read-only producer/consumer contract

## Quick start

```bash
# 1. Copy env template and fill in the keys
cp .env.example .env

# 2. Backend (requires Python 3.12 + uv)
cd backend
uv venv && uv pip sync pyproject.toml
uv run uvicorn src.main:app --reload

# 3. Frontend (slice 5 — plan 01-06)
cd frontend
npm install
npm run dev
```

## Upstream contract

The chatbot reads from the `trade-reports` index with a **Reader-role** Pinecone key
(`PINECONE_READ_KEY`). The full metadata field table, stability rules, and key-generation
process are in `docs/schema-contract.md`.

## Phase rollout

| Phase | Slices | Status |
|-------|--------|--------|
| Phase 1 — MVP | 0–5: repo bootstrap, backend, RAG chat, conversation store, SSE, frontend | In progress |
| Phase 2 — Production | 6–12: ticker extraction, live quotes, auth, Postgres, rate limiting, deployment | Planned |

## Disclaimer

This tool is for educational and research purposes only. It is NOT financial advice. It does
not execute trades, manage portfolios, or connect to any brokerage. Always do your own due
diligence and consult a licensed financial advisor before making investment decisions.
