# Architecture

## Data flow (unidirectional)

```
ai-trading-claude (producer)
  └─ /trade analyze <TICKER>
       └─ writes chunked report records → Pinecone index: trade-reports / namespace: trade
                                                    │  (read-only, Reader API key)
                                       trading-chatbot backend (Python / FastAPI)
                                         ├─ pinecone_client.py  ← query / list / fetch
                                         ├─ llm_client.py       ← OpenAI RAG assembly
                                         ├─ session_store.py    ← SQLite conversation turns
                                         └─ routes/
                                              ├─ /chat           POST  (non-streaming)
                                              ├─ /chat/stream    POST  (SSE tokens)
                                              ├─ /sessions       GET   (list)
                                              └─ /healthz /readyz GET
                                                    │  (HTTP / SSE)
                                       trading-chatbot frontend (Next.js / browser)
                                         └─ ChatWindow.tsx streams tokens + renders citations
```

**Key design decisions:**

1. **Backend is the sole Pinecone accessor.** All Pinecone queries, metadata filtering, and RAG
   prompt assembly happen in Python. The frontend knows nothing about Pinecone.

2. **Read-only consumer.** The chatbot never upserts or deletes records in `trade-reports`.
   Conversation turns are stored in the chatbot's own SQLite database (Phase 2: Postgres).

3. **Frontend talks only to the backend.** `NEXT_PUBLIC_API_BASE` points at the FastAPI server.
   No Node-side Pinecone calls.

4. **Provider-agnostic LLM wrapper.** `llm_client.py` is the single call site for OpenAI.
   Switching providers (Anthropic, local Ollama, etc.) requires editing one file.

5. **SSE streaming.** `/chat/stream` emits `event: session`, `event: citations`, N×`event: token`,
   then `event: done`. Citations are emitted once at the start so the UI can render source cards
   before the answer text is complete.

## Namespace and index

| Parameter | Value | Source |
|-----------|-------|--------|
| Index name | `trade-reports` | `PINECONE_INDEX` env var |
| Namespace | `trade` | `PINECONE_NAMESPACE` env var |
| Embedding model | `llama-text-embed-v2` | integrated inference, producer-managed |
| Cloud / region | `aws/us-east-1` | index metadata |

## Schema contract

See `docs/schema-contract.md` for the full read-only metadata field table, ID scheme,
stability rules, and key-generation process.
