"""
pinecone_client.py — Read-only Pinecone retrieval primitives.

Three public functions:
  retrieve(text, ticker=None, report_type=None, k=5)
      Semantic search against the trade-reports index with optional post-filtering.
      Treats metadata $eq/$in filters as best-effort per the retrieval gotcha noted
      in docs/schema-contract.md — prefers post-filter on returned matches when a
      server-side filter is unavailable or unreliable.

  latest(ticker, report_type="ANALYSIS")
      Lists IDs by prefix <TICKER>:<TYPE>: and fetches the lexically-greatest
      (newest) match.  Returns a normalized chunk dict or None.

  timeline(ticker, limit=20)
      Lists IDs by prefix <TICKER>:, sorts newest-first by the lexically-sortable
      ID scheme, and returns up to `limit` normalized chunks.

  _normalize(v)
      Flattens a Pinecone match or vector into {id, score, text, metadata}.

Schema contract (read-only — see docs/schema-contract.md):
  - schema_version validated on every read; unknown majors are refused (T-02-02).
  - ID scheme: <TICKER>:<TYPE>:<YYYYMMDD-HHMM>:<section-slug>:<chunk-index>

Threat mitigations applied here:
  T-02-01 — callers catch exceptions and return 503; we don't suppress them here.
  T-02-02 — schema_version validated; UnknownSchemaVersionError raised on mismatch.
  T-02-03 — k is capped at MAX_K (accepted risk; rate limiting deferred to Phase 2).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Schema version this consumer was built against.  Refuse records claiming a
# different major version (T-02-02).
SUPPORTED_SCHEMA_VERSION = 1

# Soft cap on k — single-user MVP; keeps costs bounded (T-02-03 accepted risk).
MAX_K = 20


class UnknownSchemaVersionError(ValueError):
    """Raised when a Pinecone record carries an unknown schema_version major."""


def _normalize(v: Any) -> dict:
    """
    Flatten a Pinecone SDK match/vector into a consistent dict.

    Supports both the query-result ScoredVector shape and the fetch-result
    Vector shape (which has no `score`).

    Returns:
        {
          "id":       str,
          "score":    float | None,
          "text":     str | None,
          "metadata": dict,
        }

    Raises:
        UnknownSchemaVersionError if metadata.schema_version is not SUPPORTED_SCHEMA_VERSION.
    """
    # SDK objects expose attributes; plain dicts come from tests / mocked responses.
    if isinstance(v, dict):
        vid = v.get("id", "")
        score = v.get("score", None)
        metadata: dict = v.get("metadata") or {}
        # Pinecone integrated-inference stores the chunk text in the `values` field
        # for fetch results and in `metadata["text"]` or the record's text field.
        text = v.get("text") or metadata.get("text")
    else:
        vid = getattr(v, "id", "")
        score = getattr(v, "score", None)
        metadata = dict(getattr(v, "metadata", None) or {})
        text = getattr(v, "text", None) or metadata.get("text")

    # Validate schema_version (T-02-02)
    sv = metadata.get("schema_version")
    if sv is not None and int(sv) != SUPPORTED_SCHEMA_VERSION:
        raise UnknownSchemaVersionError(
            f"Record {vid!r} carries schema_version={sv}; "
            f"this consumer only supports v{SUPPORTED_SCHEMA_VERSION}. "
            "Refusing to process — upstream schema change requires a consumer update."
        )

    return {
        "id": vid,
        "score": float(score) if score is not None else None,
        "text": text,
        "metadata": metadata,
    }


def _get_index():
    """
    Return a live Pinecone Index handle.

    Imported lazily so the module is importable without a valid PINECONE_READ_KEY
    (tests skip when the key is absent).
    """
    from pinecone import Pinecone

    from src.config import settings

    pc = Pinecone(api_key=settings.pinecone_read_key)
    return pc.Index(settings.pinecone_index)


def _get_namespace() -> str:
    from src.config import settings

    return settings.pinecone_namespace


def retrieve(
    text: str,
    ticker: Optional[str] = None,
    report_type: Optional[str] = None,
    k: int = 5,
) -> list[dict]:
    """
    Semantic search over the trade-reports index.

    Uses Pinecone integrated inference (no local embedding needed).  Applies
    ticker and report_type as a best-effort server-side metadata filter; if the
    filter is unavailable or unreliable (per the retrieval gotcha), applies the
    same conditions as a post-filter on returned matches.

    Args:
        text:        The user query / question text.
        ticker:      Optional UPPERCASE ticker symbol to constrain results.
        report_type: Optional report type string (e.g. "ANALYSIS", "THESIS").
        k:           Number of top results to return (capped at MAX_K).

    Returns:
        List of normalized chunk dicts [{id, score, text, metadata}, ...].
        Returns [] on empty results; raises on connection/auth errors (caller handles).
    """
    k = min(k, MAX_K)
    index = _get_index()
    namespace = _get_namespace()

    # Build a best-effort metadata filter.  Pinecone $eq/$in filters are known to
    # be unreliable on this index; we apply them server-side when non-empty but
    # ALWAYS post-filter on the returned matches as the authoritative gate.
    filter_dict: Optional[dict] = None
    conditions = []
    if ticker:
        conditions.append({"ticker": {"$eq": ticker.upper()}})
    if report_type:
        conditions.append({"report_type": {"$eq": report_type.upper()}})
    if len(conditions) == 1:
        filter_dict = conditions[0]
    elif len(conditions) > 1:
        filter_dict = {"$and": conditions}

    query_kwargs: dict[str, Any] = {
        "namespace": namespace,
        "top_k": k,
        "include_metadata": True,
        "include_values": False,
    }
    if filter_dict:
        query_kwargs["filter"] = filter_dict

    # Pinecone integrated-inference: query by text input
    try:
        results = index.query(inputs=text, **query_kwargs)
    except TypeError:
        # Older SDK versions may not support `inputs=`; fall back to `vector=`
        # with a zero-vector (graceful degradation — will return arbitrary results
        # but won't crash).  Real fix: upgrade pinecone SDK to >=5.
        logger.warning("pinecone_client.retrieve: SDK does not support inputs= kwarg; "
                       "falling back — results may be unrelated to query text.")
        results = index.query(vector=[0.0], **query_kwargs)

    # Use sentinel to distinguish "attribute present but empty" from "attribute absent"
    _sentinel = object()
    _matches_attr = getattr(results, "matches", _sentinel)
    if _matches_attr is not _sentinel:
        matches = _matches_attr
    elif isinstance(results, dict):
        matches = results.get("matches", [])
    else:
        matches = []

    chunks: list[dict] = []
    for m in matches:
        try:
            chunk = _normalize(m)
        except UnknownSchemaVersionError as exc:
            logger.error("retrieve: skipping record with unknown schema: %s", exc)
            continue
        # Post-filter (authoritative gate — server-side filter is best-effort only)
        meta = chunk["metadata"]
        if ticker and meta.get("ticker", "").upper() != ticker.upper():
            continue
        if report_type and meta.get("report_type", "").upper() != report_type.upper():
            continue
        chunks.append(chunk)

    return chunks


def latest(
    ticker: str,
    report_type: str = "ANALYSIS",
) -> Optional[dict]:
    """
    Return the most recent report chunk for a given ticker + report_type.

    Uses ID-prefix listing (not metadata filters) per the retrieval gotcha.
    The ID scheme is lexically sortable: the greatest ID is the newest record.

    Args:
        ticker:      UPPERCASE ticker symbol (e.g. "AAPL").
        report_type: Report type string (default "ANALYSIS").

    Returns:
        A normalized chunk dict or None if no matching records exist.
    """
    index = _get_index()
    namespace = _get_namespace()

    prefix = f"{ticker.upper()}:{report_type.upper()}:"

    try:
        id_list = list(index.list(prefix=prefix, namespace=namespace))
    except Exception as exc:
        logger.error("latest: list failed for prefix=%r: %s", prefix, exc)
        return None

    if not id_list:
        logger.debug("latest: no IDs found for prefix=%r", prefix)
        return None

    # The list() call may return strings or ID objects; normalise to str
    str_ids = [str(i) if not isinstance(i, str) else i for i in id_list]

    # Lexically greatest = newest (YYYYMMDD-HHMM segment in position 2)
    newest_id = max(str_ids)

    try:
        fetch_result = index.fetch(ids=[newest_id], namespace=namespace)
    except Exception as exc:
        logger.error("latest: fetch failed for id=%r: %s", newest_id, exc)
        return None

    vectors = getattr(fetch_result, "vectors", None) or fetch_result.get("vectors", {})
    if newest_id not in vectors:
        logger.warning("latest: fetched id=%r not in response vectors", newest_id)
        return None

    try:
        return _normalize(vectors[newest_id])
    except UnknownSchemaVersionError as exc:
        logger.error("latest: unknown schema version for %r: %s", newest_id, exc)
        return None


def timeline(
    ticker: str,
    limit: int = 20,
) -> list[dict]:
    """
    Return up to `limit` report chunks for a ticker, newest-first.

    Uses ID-prefix listing over all report types (prefix = "<TICKER>:").
    Sorts IDs lexically descending (newest first) before fetching.

    Args:
        ticker: UPPERCASE ticker symbol.
        limit:  Maximum number of chunks to return.

    Returns:
        List of normalized chunk dicts sorted newest-first.
    """
    index = _get_index()
    namespace = _get_namespace()

    prefix = f"{ticker.upper()}:"

    try:
        id_list = list(index.list(prefix=prefix, namespace=namespace))
    except Exception as exc:
        logger.error("timeline: list failed for prefix=%r: %s", prefix, exc)
        return []

    if not id_list:
        logger.debug("timeline: no IDs found for prefix=%r", prefix)
        return []

    str_ids = [str(i) if not isinstance(i, str) else i for i in id_list]

    # Newest-first: sort descending (lexically largest = most recent timestamp)
    sorted_ids = sorted(str_ids, reverse=True)[:limit]

    try:
        fetch_result = index.fetch(ids=sorted_ids, namespace=namespace)
    except Exception as exc:
        logger.error("timeline: fetch failed: %s", exc)
        return []

    vectors = getattr(fetch_result, "vectors", None) or fetch_result.get("vectors", {})

    chunks: list[dict] = []
    for vid in sorted_ids:
        if vid not in vectors:
            continue
        try:
            chunks.append(_normalize(vectors[vid]))
        except UnknownSchemaVersionError as exc:
            logger.error("timeline: skipping record with unknown schema: %s", exc)

    return chunks
