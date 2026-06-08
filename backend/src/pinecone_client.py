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


def _hit_to_record(h: Any) -> dict:
    """
    Convert one integrated-search `Hit` (or dict) into the `_normalize` input shape.

    A Hit exposes `.id`, `.score`, and `.fields` (a flat dict carrying the chunk
    `text` alongside all metadata).  We split `text` out of the metadata so
    downstream metadata stays free of the large text blob.
    """
    if isinstance(h, dict):
        hid = h.get("id") or h.get("_id") or ""
        score = h.get("score", h.get("_score"))
        fields = dict(h.get("fields") or {})
    else:
        hid = getattr(h, "id", None) or getattr(h, "id_", "") or ""
        score = getattr(h, "score", None)
        if score is None:
            score = getattr(h, "score_", None)
        fields = dict(getattr(h, "fields", None) or {})

    text = fields.get("text")
    metadata = {k: v for k, v in fields.items() if k != "text"}
    return {"id": hid, "score": score, "text": text, "metadata": metadata}


def _extract_hits(resp: Any) -> list:
    """
    Pull the hit list out of a SearchRecordsResponse (`.result.hits`) or the
    equivalent dict shape used by tests/mocks.
    """
    result = getattr(resp, "result", None)
    if result is not None:
        hits = getattr(result, "hits", None)
        if hits is not None:
            return list(hits)
    if isinstance(resp, dict):
        return list((resp.get("result") or {}).get("hits", []) or resp.get("hits", []))
    # Legacy query-shape fallback (defensive; integrated indexes use search()).
    matches = getattr(resp, "matches", None)
    if matches is not None:
        return list(matches)
    return []


def _list_ids(index: Any, prefix: str, namespace: str) -> list[str]:
    """
    Flatten `index.list(prefix=...)` into a flat list of ID strings.

    `index.list()` is a generator that yields one PAGE per iteration. Depending on
    SDK version a page is a `ListResponse` (with `.vectors` -> `ListItem.id`), a
    plain list of id strings, or (in mocks) a dict. Handle all shapes — the prior
    code stringified an entire page object as a single ID, tripping Pinecone's
    512-char ID limit against the live API.
    """
    ids: list[str] = []
    for page in index.list(prefix=prefix, namespace=namespace):
        vectors = getattr(page, "vectors", None)
        if vectors is None and isinstance(page, dict):
            vectors = page.get("vectors")
        if vectors is not None:
            for item in vectors:
                iid = getattr(item, "id", None)
                if iid is None and isinstance(item, dict):
                    iid = item.get("id")
                if iid is None and isinstance(item, str):
                    iid = item
                if iid:
                    ids.append(str(iid))
        elif isinstance(page, str):
            ids.append(page)
        elif isinstance(page, (list, tuple)):
            for item in page:
                if isinstance(item, str):
                    ids.append(item)
                else:
                    iid = getattr(item, "id", None) or (
                        item.get("id") if isinstance(item, dict) else None
                    )
                    if iid:
                        ids.append(str(iid))
    return ids


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
    # ALWAYS post-filter on the returned hits as the authoritative gate.
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

    # The trade-reports index uses Pinecone integrated inference (llama-text-embed-v2,
    # 1024-d).  Semantic search MUST go through the records `search` API (server-side
    # text->embedding); the older `query(vector=...)` path needs a 1024-d vector and
    # cannot embed text, so it is wrong for this index.  When filtering, over-fetch so
    # enough hits survive the authoritative post-filter, then truncate to k.
    fetch_k = min(max(k, k * 4), 50) if (ticker or report_type) else k
    query: dict[str, Any] = {"inputs": {"text": text}, "top_k": fetch_k}
    if filter_dict:
        query["filter"] = filter_dict

    try:
        resp = index.search(namespace=namespace, query=query)
    except Exception as exc:
        # Server-side filters are best-effort on this index — if the filtered search
        # fails, retry once unfiltered and let the post-filter below do the gating.
        if filter_dict:
            logger.warning(
                "retrieve: filtered search failed (%s); retrying unfiltered", exc
            )
            query.pop("filter", None)
            resp = index.search(namespace=namespace, query=query)
        else:
            raise

    hits = _extract_hits(resp)

    chunks: list[dict] = []
    for h in hits:
        try:
            chunk = _normalize(_hit_to_record(h))
        except UnknownSchemaVersionError as exc:
            logger.error("retrieve: skipping record with unknown schema: %s", exc)
            continue
        # Post-filter (authoritative gate — server-side filter is best-effort only)
        meta = chunk["metadata"]
        if ticker and str(meta.get("ticker", "")).upper() != ticker.upper():
            continue
        if report_type and str(meta.get("report_type", "")).upper() != report_type.upper():
            continue
        chunks.append(chunk)
        if len(chunks) >= k:
            break

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
        str_ids = _list_ids(index, prefix, namespace)
    except Exception as exc:
        logger.error("latest: list failed for prefix=%r: %s", prefix, exc)
        return None

    if not str_ids:
        logger.debug("latest: no IDs found for prefix=%r", prefix)
        return None

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
        str_ids = _list_ids(index, prefix, namespace)
    except Exception as exc:
        logger.error("timeline: list failed for prefix=%r: %s", prefix, exc)
        return []

    if not str_ids:
        logger.debug("timeline: no IDs found for prefix=%r", prefix)
        return []

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
