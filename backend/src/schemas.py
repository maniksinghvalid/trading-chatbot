"""
schemas.py — Shared Pydantic models for the trading-chatbot API.

These are the locked contract between the backend and frontend (see 01-CONTEXT.md).
Do NOT change field names or types without a coordinated frontend migration.

Models:
  ChatRequest  — user message payload (POST /chat, POST /chat/stream)
  Citation     — a single source chunk cited in a response
  ChatResponse — the response from POST /chat (non-streaming)
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Incoming chat request from the frontend.

    Fields:
        message:    The user's natural-language question (required).
        ticker:     Optional UPPERCASE ticker symbol scoping the retrieval (e.g. "AAPL").
                    Slice 2 requires the caller to pass this explicitly; auto-extraction
                    is deferred to Phase 2 (slice 6).
        session_id: Optional existing session UUID.  When absent the backend mints a
                    new uuid4 and returns it in ChatResponse.session_id.
    """

    message: str
    ticker: Optional[str] = None
    session_id: Optional[str] = None


class Citation(BaseModel):
    """Metadata for a single source chunk cited in a response.

    Fields mirror the upstream Pinecone record schema (read-only contract).
    See docs/schema-contract.md for the full field table.

    Fields:
        source_path:    Path / identifier of the originating trade report file.
        generated_date: Date the source report was generated (YYYYMMDD or ISO string).
        ticker:         Ticker symbol from the record metadata.
        report_type:    Report type (e.g. "ANALYSIS", "TECHNICAL", "OPTIONS").
    """

    source_path: str
    generated_date: str
    ticker: str
    report_type: str


class ChatResponse(BaseModel):
    """Response from POST /chat (non-streaming).

    Fields:
        message:    The assistant's grounded answer, including inline source citations
                    in [src:<source_path>:<generated_date>] format and the disclaimer.
        citations:  List of Citation objects for every source chunk used.
                    EMPTY LIST when no data exists for the ticker (no-data path).
                    Never fabricated — built only from real retrieved chunk metadata.
        session_id: UUID identifying this conversation session.  A new uuid4 when the
                    request did not supply one.
    """

    message: str
    citations: list[Citation]
    session_id: str
