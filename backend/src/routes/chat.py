"""
routes/chat.py — POST /chat RAG endpoint.

Five-step flow:
  1. Retrieve up to k=6 semantic chunks from Pinecone (with optional ticker scope).
  2. Build the grounded user prompt via rag_user_prompt().
  3. Call llm_client.complete() with SYSTEM_PROMPT + user prompt.
  4. Build a Citation object per retrieved chunk from its metadata.
  5. Return ChatResponse (new uuid4 session_id when none was supplied).

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

logger = logging.getLogger(__name__)

router = APIRouter()

# Number of chunks to retrieve per query (bounded for cost + context size — T-03-04)
_RETRIEVE_K: int = 6


@router.post("/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming RAG chat endpoint.

    Retrieves relevant chunks from Pinecone, assembles a grounded prompt, calls
    the LLM, and returns a cited answer.

    The no-data path fires when Pinecone returns zero chunks: the response is a
    graceful "I don't have stored analysis for <TICKER>" message with an empty
    citations list — never a fabricated citation (VERIFY-NODATA / T-03-02).
    """
    # Mint a session_id if the caller did not supply one
    session_id: str = req.session_id or str(uuid.uuid4())

    # --- Step 1: Retrieve chunks ---
    ticker_upper = req.ticker.upper() if req.ticker else None
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
        return ChatResponse(
            message=graceful_message,
            citations=[],
            session_id=session_id,
        )

    # --- Step 2: Build grounded user prompt ---
    user_prompt = rag_user_prompt(req.message, chunks)

    # --- Step 3: Call LLM ---
    try:
        answer = complete(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except LLMProviderError as exc:
        logger.error("post_chat: LLM provider error: %s", exc)
        raise HTTPException(status_code=503, detail="LLM provider unavailable") from exc

    # --- Step 4: Build citations from real chunk metadata only (T-03-02) ---
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

    # --- Step 5: Return ChatResponse ---
    return ChatResponse(
        message=answer,
        citations=citations,
        session_id=session_id,
    )
