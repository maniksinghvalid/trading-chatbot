"""
routes/health.py — /healthz and /readyz endpoints.

/healthz  — fast liveness check; never touches external services.
/readyz   — readiness check that opens the Pinecone index and reads describe_index_stats().
             Returns 200 + vector_count on success; 503 + a generic error body on failure.
             Per T-02-01 (threat model): NEVER leak the API key or a Python stack trace in
             the 503 body.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    """Fast liveness probe — always returns 200 {status: 'ok'}."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """
    Readiness probe.

    Connects to the Pinecone index and returns the current vector count from
    describe_index_stats().  Returns 503 with a generic message on any error —
    never the raw exception or API key.
    """
    try:
        from pinecone import Pinecone  # imported here to avoid import-time failures when key absent

        from src.config import settings

        pc = Pinecone(api_key=settings.pinecone_read_key)
        index = pc.Index(settings.pinecone_index)
        stats = index.describe_index_stats()

        # Aggregate across all namespaces for the total vector count
        total_vectors: int = stats.get("total_vector_count", 0)
        # If the SDK returns a typed object use attribute access as fallback
        if hasattr(stats, "total_vector_count"):
            total_vectors = stats.total_vector_count  # type: ignore[assignment]

        return JSONResponse(
            status_code=200,
            content={"status": "ok", "vector_count": total_vectors},
        )
    except Exception as exc:
        # Log internally (for operator visibility) but never surface to the caller
        logger.error("readyz: Pinecone connection failed: %s", exc, exc_info=False)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "memory unavailable"},
        )
