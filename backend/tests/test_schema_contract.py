"""
test_schema_contract.py — VERIFY-SCHEMA regression test.

Asserts that the upstream Pinecone record metadata carries all required fields
as declared in docs/schema-contract.md (the producer/consumer contract).

This test is marked @pytest.mark.live_index — it requires a live PINECONE_READ_KEY.
When the key is unset, conftest.py auto-skips the test cleanly (appears as 's'
in pytest output, not 'F') so the full suite stays green without credentials.

Required metadata fields (always present per contract):
  ticker          — UPPERCASE ticker symbol
  report_type     — one of the report_type enum values
  generated_at    — ISO-8601 full timestamp with tz offset
  generated_date  — YYYY-MM-DD date string
  source_path     — original filename for citation rendering

On failure, the test names the missing field explicitly so CI output is
immediately actionable ("generated_at missing from AAPL ANALYSIS chunk").
"""

from __future__ import annotations

import pytest

from src.pinecone_client import retrieve

# The five fields that must ALWAYS be present and non-empty per the contract.
# (schema-contract.md: "Always present? yes")
REQUIRED_FIELDS: list[str] = [
    "ticker",
    "report_type",
    "generated_at",
    "generated_date",
    "source_path",
]


@pytest.mark.live_index
def test_required_metadata_fields_present() -> None:
    """VERIFY-SCHEMA: all required metadata fields are present and non-empty.

    Calls retrieve("AAPL", k=1) and asserts every field in REQUIRED_FIELDS
    is present in the first chunk's metadata and has a non-empty value.

    Fails loudly naming the missing / empty field so the CI log is actionable.

    Skips automatically when PINECONE_READ_KEY is not set (conftest.py).
    """
    chunks = retrieve("AAPL recent analysis", ticker="AAPL", k=1)

    assert chunks, (
        "retrieve('AAPL recent analysis', ticker='AAPL', k=1) returned no chunks. "
        "Ensure the trade-reports index has at least one AAPL record."
    )

    chunk = chunks[0]
    metadata = chunk.get("metadata") or {}

    for field in REQUIRED_FIELDS:
        value = metadata.get(field)
        assert value is not None and str(value).strip(), (
            f"VERIFY-SCHEMA FAILED: required metadata field '{field}' is "
            f"{'missing' if value is None else 'empty'} in AAPL chunk "
            f"(id={chunk.get('id')!r}). "
            f"This indicates an upstream schema change — check trade_schemas.py "
            f"and docs/schema-contract.md."
        )
