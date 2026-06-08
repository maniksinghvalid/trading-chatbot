#!/usr/bin/env python3
"""
smoke_index.py — Live-index smoke test for the trade-reports Pinecone index.

No application code, no FastAPI. Reads environment variables, opens the index,
calls describe_index_stats(), and prints the namespace list + total vector count.

Exits:
  0  — smoke passed (namespace found, or graceful skip when key is absent)
  1  — smoke failed (auth error, index not found, or unexpected exception)

Usage:
  # With a real Reader key:
  PINECONE_READ_KEY=<key> python scripts/smoke_index.py

  # Without a key (safe to run in CI — prints skip message and exits 0):
  python scripts/smoke_index.py

Requirements:
  pip install "pinecone>=5"
"""

import os
import sys


def main() -> int:
    read_key = os.environ.get("PINECONE_READ_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX", "trade-reports").strip()
    namespace = os.environ.get("PINECONE_NAMESPACE", "trade").strip()

    # ------------------------------------------------------------------ #
    # Gate 0 — skip cleanly when no key is configured                     #
    # ------------------------------------------------------------------ #
    if not read_key:
        print("PINECONE_READ_KEY not set — skipping live-index smoke (exit 0).")
        print(
            "To run: export PINECONE_READ_KEY=<reader-key> && python scripts/smoke_index.py"
        )
        return 0

    # ------------------------------------------------------------------ #
    # Gate 1 — import check                                               #
    # ------------------------------------------------------------------ #
    try:
        from pinecone import Pinecone  # type: ignore[import]
    except ImportError:
        print(
            "ERROR: 'pinecone' package not found. Install with: pip install 'pinecone>=5'",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------ #
    # Gate 2 — connect + describe                                         #
    # ------------------------------------------------------------------ #
    try:
        pc = Pinecone(api_key=read_key)
        index = pc.Index(index_name)
        stats = index.describe_index_stats()
    except Exception as exc:  # noqa: BLE001
        # Surface auth errors, missing-index errors, and network failures
        # without a traceback — the message is enough for the smoke gate.
        print(f"ERROR: describe_index_stats() failed: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------ #
    # Gate 3 — interpret results                                          #
    # ------------------------------------------------------------------ #
    total_vectors = getattr(stats, "total_vector_count", None)
    if total_vectors is None:
        # SDK version difference: try dict-style access
        try:
            total_vectors = stats["total_vector_count"]
        except (KeyError, TypeError):
            total_vectors = "unknown"

    namespaces = {}
    try:
        namespaces = stats.namespaces or {}
    except AttributeError:
        try:
            namespaces = stats.get("namespaces", {}) or {}
        except AttributeError:
            pass

    print(f"Index:          {index_name}")
    print(f"Total vectors:  {total_vectors}")
    print(f"Namespaces found: {list(namespaces.keys()) if namespaces else '(none)'}")

    # ------------------------------------------------------------------ #
    # Gate 4 — check the target namespace specifically                    #
    # ------------------------------------------------------------------ #
    if not namespaces:
        print(
            f"\nWARNING: No namespaces found in index '{index_name}'. "
            "The producer may not have ingested any records yet. "
            "This is acceptable for slice 0 (the chatbot is consumer-only)."
        )
        return 0

    if namespace in namespaces:
        ns_info = namespaces[namespace]
        try:
            ns_count = getattr(ns_info, "vector_count", None) or ns_info.get(
                "vector_count", 0
            )
        except AttributeError:
            ns_count = 0

        if ns_count and ns_count > 0:
            print(f"\nSMOKE PASSED: namespace '{namespace}' has {ns_count} vectors.")
        else:
            print(
                f"\nSMOKE PASSED (namespace empty): namespace '{namespace}' exists "
                "but has 0 vectors. Acceptable for slice 0 — the producer has not "
                "ingested records yet."
            )
    else:
        print(
            f"\nWARNING: namespace '{namespace}' not found in index '{index_name}'. "
            f"Available namespaces: {list(namespaces.keys())}. "
            "The producer may not have ingested any records yet. "
            "This is acceptable for slice 0."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
