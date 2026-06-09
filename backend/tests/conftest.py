"""
conftest.py — shared pytest fixtures and markers for the backend test suite.

Live-index tests are marked with @pytest.mark.live_index.
These tests skip cleanly when PINECONE_READ_KEY is unset (or empty), so the
full suite stays green in environments without credentials.

Postgres integration tests are marked with @pytest.mark.postgres.
These tests skip cleanly when DATABASE_URL is unset or is a SQLite URL,
so the full suite stays green without a running Postgres instance.

Usage in test files:
    @pytest.mark.live_index
    def test_something():
        ...

    @pytest.mark.postgres
    def test_postgres_something():
        ...

To run live tests:
    export PINECONE_READ_KEY=<your-reader-key>
    cd backend && uv run pytest

To run Postgres integration tests:
    docker compose up -d          # (from trading-chatbot/)
    export DATABASE_URL=postgresql+psycopg://chatbot:chatbot@localhost:5432/chatbot
    cd backend && uv run pytest -m postgres
"""

import os

import pytest


def _pinecone_key_present() -> bool:
    """Return True if a non-empty PINECONE_READ_KEY is configured."""
    key = os.environ.get("PINECONE_READ_KEY", "").strip()
    return bool(key)


def _postgres_dsn_present() -> bool:
    """Return True if DATABASE_URL is set and points at a Postgres database."""
    url = os.environ.get("DATABASE_URL", "").strip()
    return url.startswith("postgresql")


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so pytest doesn't warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "live_index: marks tests that require a live Pinecone index "
        "(skipped when PINECONE_READ_KEY is unset)",
    )
    config.addinivalue_line(
        "markers",
        "postgres: marks tests that require a live Postgres database "
        "(skipped when DATABASE_URL is unset or is a SQLite URL)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """
    Auto-skip live_index tests when PINECONE_READ_KEY is absent.
    Auto-skip postgres tests when DATABASE_URL is absent or SQLite.

    This runs before any test, so skipped tests appear as 's' (not 'F')
    in the pytest output — the suite remains green without credentials.
    """
    skip_live = pytest.mark.skip(
        reason="PINECONE_READ_KEY not set — skipping live-index smoke tests"
    )
    skip_pg = pytest.mark.skip(
        reason="DATABASE_URL not set to a Postgres DSN — skipping Postgres integration tests"
    )

    pinecone_ok = _pinecone_key_present()
    postgres_ok = _postgres_dsn_present()

    for item in items:
        if not pinecone_ok and item.get_closest_marker("live_index"):
            item.add_marker(skip_live)
        if not postgres_ok and item.get_closest_marker("postgres"):
            item.add_marker(skip_pg)


@pytest.fixture(scope="session")
def pinecone_key_present() -> bool:
    """Boolean fixture: True when a live Pinecone key is configured."""
    return _pinecone_key_present()


@pytest.fixture(scope="session")
def postgres_dsn_present() -> bool:
    """Boolean fixture: True when DATABASE_URL is set to a Postgres DSN."""
    return _postgres_dsn_present()
