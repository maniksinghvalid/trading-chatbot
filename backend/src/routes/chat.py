"""
routes/chat.py — POST /chat (non-streaming) and POST /chat/stream (SSE) endpoints.

Non-streaming flow (POST /chat, slice 2–3):
  1. Resolve session_id + load prior conversation history.
  2. Extract tickers from message via extract_tickers(); classify intent via classify_intent().
     Ticker resolution order: explicit req.ticker > first extracted ticker > coreference from
     session history (ticker_scope inheritance). (Slice 6 / TICK-01)
  3. Retrieve up to k=6 semantic chunks from Pinecone.
     Coreference: when req.ticker is None and extraction finds nothing, inherit the most recent
     non-null ticker_scope from the session history so follow-up turns stay on the in-scope
     ticker (T-04-02: parameterized queries only — no string SQL).
  4. Build the grounded user prompt via rag_user_prompt(), with live_quote when intent-gated.
  5. Call llm_client.complete() with SYSTEM_PROMPT + history messages + user prompt.
  6. Persist user + assistant turns; return ChatResponse.

Streaming flow (POST /chat/stream, slice 4):
  Same steps 1–4, then:
  5. Open an SSE EventSourceResponse that emits events in order (01-CONTEXT.md locked order):
       event: session    (the session_id)
       event: citations  (JSON list of Citation objects — once, up front)
       event: quote      (JSON quote dict — ONLY for price-intent requests, slice 7)
       event: token      (one per yielded chunk from stream_complete)
       event: done
  6. Buffer all tokens; on completion append_turn for user + assistant.
  7. Mid-stream LLMProviderError → emit a terminating error event then done,
     never leaking key material or stack traces (T-05-02).

No-data path (VERIFY-NODATA, T-03-02):
  When retrieve() returns zero chunks the route short-circuits to a graceful
  fixed response: "I don't have stored analysis for <TICKER>; would you like
  live market data instead?" with citations=[].  No fabricated citations, no
  hallucinated source paths.  The streaming variant emits the graceful message
  as a single token event so the frontend can render it incrementally.

Error handling (T-03-03 / T-05-02):
  LLMProviderError from llm_client → HTTP 503 (non-streaming) or a terminating
  SSE error event + done (streaming).  No key or stack trace in the response.

Live-quote intent gating (slice 7 / QUOTE-01):
  A quote is fetched ONLY when intent=="factual" AND a price-keyword family
  (now/current/today/price/"trading at"/quote) is present in the message AND
  a ticker is resolved.  Outlook/thesis questions pass live_quote=None and
  emit no quote event.  QuoteUnavailableError degrades gracefully (live_quote=None);
  the chat continues without a quote rather than failing the request.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.auth import get_current_user
from src.intent_classifier import classify_intent
from src.llm_client import LLMProviderError, complete, stream_complete
import src.market_data as market_data
from src.market_data import QuoteUnavailableError
from src.pinecone_client import retrieve
from src.prompts import SYSTEM_PROMPT, rag_user_prompt
from src.rate_limiter import BudgetExceeded, check_and_increment
from src.schemas import ChatRequest, ChatResponse, Citation
from src.session_store import append_turn, history
from src.ticker_extractor import extract_tickers

logger = logging.getLogger(__name__)

router = APIRouter()

# Number of chunks to retrieve per query (bounded for cost + context size — T-03-04)
_RETRIEVE_K: int = 6

# History window sent to the LLM (limits context size and cost)
_HISTORY_LIMIT: int = 10

# Price-keyword family (slice 7): triggers live-quote fetch when intent=="factual"
# and the message contains at least one of these terms (case-insensitive).
_PRICE_KEYWORDS: frozenset[str] = frozenset(
    {"now", "current", "today", "price", "trading at", "quote"}
)


def _wants_live_quote(intent: str, message: str, ticker: str | None) -> bool:
    """Return True when a live price quote should be fetched.

    Criteria (all three must hold):
      - intent is "factual" (classifier signal)
      - at least one price keyword is present in the (lowercased) message
      - an effective ticker has been resolved (not None)
    """
    if intent != "factual" or ticker is None:
        return False
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _PRICE_KEYWORDS)


@router.post("/chat", response_model=ChatResponse)
def post_chat(
    req: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> ChatResponse:
    """Non-streaming RAG chat endpoint with conversation history.

    Requires a valid Bearer JWT in the Authorization header (AUTH-01).
    Unauthenticated requests receive HTTP 401.

    Loads prior turns from the session store so the LLM has multi-turn context.
    Coreference: if req.ticker is None, the most recent non-null ticker_scope
    from prior turns is used for Pinecone retrieval, so "what about risks?"
    correctly retrieves AAPL context when AAPL was the prior-turn ticker.

    The no-data path fires when Pinecone returns zero chunks: the response is a
    graceful "I don't have stored analysis for <TICKER>" message with an empty
    citations list — never a fabricated citation (VERIFY-NODATA / T-03-02).
    """
    # --- Rate limit gate (RATE-01): check per-user daily budget BEFORE any work ---
    # user_id is taken from the validated JWT (T-02-05-03 — not from request body).
    try:
        check_and_increment(user_id)
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="daily budget exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    # --- Step 1: Resolve session_id + load history ---
    session_id: str = req.session_id or str(uuid.uuid4())

    prior_turns = history(session_id, limit=_HISTORY_LIMIT)

    # --- Slice 6 / TICK-01: Extract tickers + classify intent from the message ---
    # extract_tickers() handles both explicit symbols and company-name mentions.
    extracted = extract_tickers(req.message)
    # classify_intent() drives slice 7 live-quote gating.
    intent_result = classify_intent(req.message)
    intent = intent_result.get("intent", "factual")

    # Ticker resolution order (three-tier fallback):
    #   1. Explicit req.ticker (caller-supplied, highest precedence)
    #   2. First ticker extracted from the message text (TICK-01)
    #   3. Coreference: inherit most-recent non-null ticker_scope from history
    if req.ticker is not None:
        effective_ticker: str | None = req.ticker.upper()
    elif extracted:
        effective_ticker = extracted[0]
    else:
        effective_ticker = next(
            (t.ticker_scope for t in reversed(prior_turns) if t.ticker_scope),
            None,
        )

    ticker_upper = effective_ticker  # may be None

    # --- Step 2: Retrieve chunks ---
    try:
        chunks = retrieve(req.message, ticker=ticker_upper, k=_RETRIEVE_K)
    except Exception as exc:
        logger.error("post_chat: Pinecone retrieval failed: %s", exc)
        # Graceful degradation: treat retrieval failure as no-data
        chunks = []

    # --- No-data path (VERIFY-NODATA) ---
    if not chunks:
        ticker_label = ticker_upper or "the requested ticker"
        graceful_message = (
            f"I don't have stored analysis for {ticker_label}; "
            "would you like live market data instead?"
        )
        # Still persist the user turn so the session is meaningful for history
        append_turn(session_id, "user", req.message, ticker=req.ticker, user_id=user_id)
        append_turn(session_id, "assistant", graceful_message, ticker=ticker_upper, user_id=user_id)
        return ChatResponse(
            message=graceful_message,
            citations=[],
            session_id=session_id,
        )

    # --- Slice 7 / QUOTE-01: Fetch live quote when price-intent detected ---
    # Degrades gracefully on QuoteUnavailableError — chat continues without quote.
    live_quote = None
    if _wants_live_quote(intent, req.message, ticker_upper):
        try:
            live_quote = market_data.quote(ticker_upper)
            logger.info("post_chat: fetched live quote for %s", ticker_upper)
        except QuoteUnavailableError as exc:
            logger.warning("post_chat: quote unavailable for %s: %s", ticker_upper, exc)
            live_quote = None  # degrade gracefully

    # --- Step 3: Build messages list (history + new grounded user prompt) ---
    # Convert prior turns into the OpenAI messages format so the LLM has context
    history_messages: list[dict] = [
        {"role": t.role, "content": t.content}
        for t in prior_turns
    ]

    user_prompt = rag_user_prompt(req.message, chunks, live_quote=live_quote)
    messages = history_messages + [{"role": "user", "content": user_prompt}]

    # --- Step 4: Call LLM ---
    try:
        answer = complete(
            system=SYSTEM_PROMPT,
            messages=messages,
        )
    except LLMProviderError as exc:
        logger.error("post_chat: LLM provider error: %s", exc)
        raise HTTPException(status_code=503, detail="LLM provider unavailable") from exc

    # --- Step 5: Build citations from real chunk metadata only (T-03-02) ---
    citations: list[Citation] = []
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        source_path = meta.get("source_path", "")
        generated_date = meta.get("generated_date", "")
        chunk_ticker = meta.get("ticker", "")
        report_type = meta.get("report_type", "")

        # Only include citation if we have the minimum required fields
        if source_path and generated_date and chunk_ticker and report_type:
            citations.append(
                Citation(
                    source_path=source_path,
                    generated_date=generated_date,
                    ticker=chunk_ticker,
                    report_type=report_type,
                )
            )

    # --- Step 6: Persist both turns and return ChatResponse ---
    # Record retrieved chunk IDs on the assistant turn for audit (DB-01).
    chunk_ids: list[str] = [c["id"] for c in chunks if c.get("id")]
    append_turn(session_id, "user", req.message, ticker=req.ticker, user_id=user_id)
    append_turn(
        session_id, "assistant", answer, ticker=ticker_upper, user_id=user_id,
        retrieved_chunk_ids=chunk_ids,
    )

    return ChatResponse(
        message=answer,
        citations=citations,
        session_id=session_id,
    )


@router.post("/chat/stream")
def post_chat_stream(
    req: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> EventSourceResponse:
    """Streaming SSE RAG chat endpoint (slice 4).

    Requires a valid Bearer JWT in the Authorization header (AUTH-01).
    Unauthenticated requests receive HTTP 401.

    Emits SSE events in the locked order (01-CONTEXT.md):
      1. event: session   — the session_id (minted or supplied)
      2. event: citations — JSON list of Citation objects, once up front
      3. event: token     — one per token yielded by stream_complete
      4. event: done      — signals the stream is complete

    Full assistant text is buffered and both user + assistant turns are
    persisted to the session store on completion.

    Mid-stream LLMProviderError emits a terminating `event: error` then
    `event: done` — no key material or stack trace in the payload (T-05-02).

    Citations are serialised from real chunk metadata (T-05-03 — no injection).
    """

    async def _event_generator() -> AsyncGenerator[dict, None]:
        # --- Step 1: Resolve session_id + load history ---
        session_id: str = req.session_id or str(uuid.uuid4())
        prior_turns = history(session_id, limit=_HISTORY_LIMIT)

        # Emit session event immediately so the client has the ID
        yield {"event": "session", "data": session_id}

        # --- Slice 6 / TICK-01: Extract tickers + classify intent from the message ---
        extracted = extract_tickers(req.message)
        # classify_intent() drives slice 7 live-quote gating.
        intent_result = classify_intent(req.message)
        intent = intent_result.get("intent", "factual")

        # Ticker resolution order (three-tier fallback):
        #   1. Explicit req.ticker (caller-supplied, highest precedence)
        #   2. First ticker extracted from the message text (TICK-01)
        #   3. Coreference: inherit most-recent non-null ticker_scope from history
        if req.ticker is not None:
            effective_ticker = req.ticker.upper()
        elif extracted:
            effective_ticker = extracted[0]
        else:
            effective_ticker = next(
                (t.ticker_scope for t in reversed(prior_turns) if t.ticker_scope),
                None,
            )

        ticker_upper = effective_ticker  # may be None

        # --- Step 2: Retrieve chunks ---
        try:
            chunks = retrieve(req.message, ticker=ticker_upper, k=_RETRIEVE_K)
        except Exception as exc:
            logger.error("post_chat_stream: Pinecone retrieval failed: %s", exc)
            chunks = []

        # --- Build citations list from real chunk metadata only (T-05-03) ---
        citations: list[Citation] = []
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            source_path = meta.get("source_path", "")
            generated_date = meta.get("generated_date", "")
            chunk_ticker = meta.get("ticker", "")
            report_type = meta.get("report_type", "")
            if source_path and generated_date and chunk_ticker and report_type:
                citations.append(
                    Citation(
                        source_path=source_path,
                        generated_date=generated_date,
                        ticker=chunk_ticker,
                        report_type=report_type,
                    )
                )

        # --- Emit citations event ONCE, before any token (01-CONTEXT.md locked order) ---
        yield {
            "event": "citations",
            "data": json.dumps([c.model_dump() for c in citations]),
        }

        # --- No-data path: graceful message as a single token, then done ---
        if not chunks:
            ticker_label = ticker_upper or "the requested ticker"
            graceful_message = (
                f"I don't have stored analysis for {ticker_label}; "
                "would you like live market data instead?"
            )
            yield {"event": "token", "data": graceful_message}
            append_turn(session_id, "user", req.message, ticker=req.ticker, user_id=user_id)
            append_turn(session_id, "assistant", graceful_message, ticker=ticker_upper, user_id=user_id)
            yield {"event": "done", "data": ""}
            return

        # --- Slice 7 / QUOTE-01: Fetch live quote + emit quote event (price-intent only) ---
        # The event: quote is emitted AFTER citations and BEFORE the first token,
        # extending the locked SSE order without reordering existing events.
        live_quote = None
        if _wants_live_quote(intent, req.message, ticker_upper):
            try:
                live_quote = market_data.quote(ticker_upper)
                logger.info("post_chat_stream: fetched live quote for %s", ticker_upper)
                yield {
                    "event": "quote",
                    "data": json.dumps(live_quote),
                }
            except QuoteUnavailableError as exc:
                logger.warning(
                    "post_chat_stream: quote unavailable for %s: %s", ticker_upper, exc
                )
                live_quote = None  # degrade gracefully; no quote event emitted

        # --- Step 3: Build messages list (history + new grounded user prompt) ---
        history_messages: list[dict] = [
            {"role": t.role, "content": t.content}
            for t in prior_turns
        ]
        user_prompt = rag_user_prompt(req.message, chunks, live_quote=live_quote)
        messages = history_messages + [{"role": "user", "content": user_prompt}]

        # --- Step 4: Stream tokens, buffering for persistence ---
        full_response_parts: list[str] = []
        try:
            for token in stream_complete(system=SYSTEM_PROMPT, messages=messages):
                full_response_parts.append(token)
                yield {"event": "token", "data": token}
        except LLMProviderError as exc:
            logger.error("post_chat_stream: LLM provider error mid-stream: %s", exc)
            # Emit a terminating error event — no key/stack trace (T-05-02)
            yield {"event": "error", "data": "LLM provider unavailable"}
            yield {"event": "done", "data": ""}
            return

        # --- Step 5: Persist both turns on completion ---
        # Record retrieved chunk IDs on the assistant turn for audit (DB-01).
        chunk_ids: list[str] = [c["id"] for c in chunks if c.get("id")]
        assistant_text = "".join(full_response_parts)
        append_turn(session_id, "user", req.message, ticker=req.ticker, user_id=user_id)
        append_turn(
            session_id, "assistant", assistant_text, ticker=ticker_upper, user_id=user_id,
            retrieved_chunk_ids=chunk_ids,
        )

        yield {"event": "done", "data": ""}

    # --- Rate limit gate (RATE-01): check BEFORE opening SSE stream ---
    # Must be checked here (not inside _event_generator) so a 429 is a normal
    # HTTP response rather than an SSE event — client can read Retry-After header.
    # user_id comes from the JWT (T-02-05-03 — not from request body).
    try:
        check_and_increment(user_id)
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="daily budget exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    return EventSourceResponse(_event_generator())
