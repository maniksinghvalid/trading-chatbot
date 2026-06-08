"""
conftest.py — shared pytest fixtures and markers for the backend test suite.

Live-index tests are marked with @pytest.mark.live_index.
These tests skip cleanly when PINECONE_READ_KEY is unset (or empty), so the
full suite stays green in environments without credentials.

Usage in test files:
    @pytest.mark.live_index
    def test_something():
        ...

To run live tests:
    export PINECONE_READ_KEY=<your-reader-key>
    cd backend && uv run pytest
"""

import os

import pytest


def _pinecone_key_present() -> bool:
    """Return True if a non-empty PINECONE_READ_KEY is configured."""
    key = os.environ.get("PINECONE_READ_KEY", "").strip()
    return bool(key)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so pytest doesn't warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "live_index: marks tests that require a live Pinecone index "
        "(skipped when PINECONE_READ_KEY is unset)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """
    Auto-skip live_index tests when PINECONE_READ_KEY is absent.

    This runs before any test, so skipped tests appear as 's' (not 'F')
    in the pytest output — the suite remains green without credentials.
    """
    if _pinecone_key_present():
        return  # key is present — let live tests run normally

    skip_reason = pytest.mark.skip(
        reason="PINECONE_READ_KEY not set — skipping live-index smoke tests"
    )
    for item in items:
        if item.get_closest_marker("live_index"):
            item.add_marker(skip_reason)


@pytest.fixture(scope="session")
def pinecone_key_present() -> bool:
    """Boolean fixture: True when a live Pinecone key is configured."""
    return _pinecone_key_present()
