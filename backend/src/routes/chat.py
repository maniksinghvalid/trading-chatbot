"""
routes/chat.py — POST /chat RAG endpoint (history-aware, slice 3).

Five-step flow:
  1. Resolve session_id + load prior conversation history.
  2. Retrieve up to k=6 semantic chunks from Pinecone.
     Coreference: when req.ticker is None, inherit the most recent non-null
     ticker_scope from the session history so follow-up turns stay on the
     in-scope ticker (T-04-02: parameterized queries only — no string SQL).
  3. Build the grounded user prompt via rag_user_prompt().
  4. Call llm_client.complete() with SYSTEM_PROMPT + history messages + user prompt.
  5. Persist user + assistant turns; return ChatResponse.

No-data path (VERIFY-NODATA, T-03-02):
  When retrieve() returns zero chunks the route short-circuits to a graceful
  fixed response: "I don't have stored analysis for <TICKER>; would you like
  live market data instead?" with citations=[].  No fabricated citations, no
  hallucinated source paths.

Error handling (T-03-03):
  LLMProviderError from llm_client → HTTP 503 with generic body "LLM provider
  unavailable". No key or stack trace is included in the response.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from src.llm_client import LLMProviderError, complete
from src.pinecone_client import retrieve
from src.prompts import SYSTEM_PROMPT, rag_user_prompt
from src.schemas import ChatRequest, ChatResponse, Citation
from src.session_store import append_turn, history

logger = logging.getLogger(__name__)

router = APIRouter()

# Number of chunks to retrieve per query (bounded for cost + context size — T-03-04)
_RETRIEVE_K: int = 6

# History window sent to the LLM (limits context size and cost)
_HISTORY_LIMIT: int = 10


@router.post("/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming RAG chat endpoint with conversation history.

    Loads prior turns from the session store so the LLM has multi-turn context.
    Coreference: if req.ticker is None, the most recent non-null ticker_scope
    from prior turns is used for Pinecone retrieval, so "what about risks?"
    correctly retrieves AAPL context when AAPL was the prior-turn ticker.

    The no-data path fires when Pinecone returns zero chunks: the response is a
    graceful "I don't have stored analysis for <TICKER>" message with an empty
    citations list — never a fabricated citation (VERIFY-NODATA / T-03-02).
    """
    # --- Step 1: Resolve session_id + load history ---
    session_id: str = req.session_id or str(uuid.uuid4())

    prior_turns = history(session_id, limit=_HISTORY_LIMIT)

    # Coreference: inherit the most recent non-null ticker_scope from history
    # when the caller doesn't supply an explicit ticker.
    if req.ticker is not None:
        effective_ticker = req.ticker.upper()
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
        append_turn(session_id, "user", req.message, ticker=req.ticker)
        append_turn(session_id, "assistant", graceful_message, ticker=ticker_upper)
        return ChatResponse(
            message=graceful_message,
            citations=[],
            session_id=session_id,
        )

    # --- Step 3: Build messages list (history + new grounded user prompt) ---
    # Convert prior turns into the OpenAI messages format so the LLM has context
    history_messages: list[dict] = [
        {"role": t.role, "content": t.content}
        for t in prior_turns
    ]

    user_prompt = rag_user_prompt(req.message, chunks)
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
    append_turn(session_id, "user", req.message, ticker=req.ticker)
    append_turn(session_id, "assistant", answer, ticker=ticker_upper)

    return ChatResponse(
        message=answer,
        citations=citations,
        session_id=session_id,
    )
