"""
test_pinecone_client.py — Unit + live-index smoke tests for pinecone_client.py.

Unit tests (no marker) run always — they exercise _normalize and error paths
using plain dicts / mocked objects without touching Pinecone.

Live-index smoke tests (@pytest.mark.live_index) skip when PINECONE_READ_KEY
is absent.  When a real key is set they hit the live trade-reports index and
verify the three retrieval primitives return the expected shapes.
"""

import pytest

# ---------------------------------------------------------------------------
# Unit tests — _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    """Tests for the _normalize() helper — no live Pinecone required."""

    def setup_method(self) -> None:
        # Import here so we get a fresh module reference in each test run.
        from src.pinecone_client import _normalize  # noqa: F401
        self._normalize = _normalize

    def test_normalize_dict_with_score(self) -> None:
        v = {
            "id": "AAPL:ANALYSIS:20260530-1430:exec-summary:0",
            "score": 0.87,
            "metadata": {
                "schema_version": 1,
                "ticker": "AAPL",
                "report_type": "ANALYSIS",
                "generated_at": "2026-05-30T14:30:00+00:00",
                "generated_date": "2026-05-30",
                "source_path": "TRADE-ANALYSIS-AAPL.md",
                "section": "exec-summary",
                "chunk_index": 0,
                "text": "Apple reported strong earnings.",
            },
        }
        chunk = self._normalize(v)
        assert chunk["id"] == v["id"]
        assert chunk["score"] == pytest.approx(0.87)
        assert chunk["metadata"]["ticker"] == "AAPL"
        assert isinstance(chunk["metadata"], dict)

    def test_normalize_dict_text_in_top_level(self) -> None:
        """text field at top level takes precedence over metadata["text"]."""
        v = {
            "id": "NVDA:THESIS:20260601-0900:intro:0",
            "score": 0.75,
            "text": "NVDA thesis text",
            "metadata": {"schema_version": 1, "ticker": "NVDA", "report_type": "THESIS",
                         "generated_at": "2026-06-01T09:00:00+00:00"},
        }
        chunk = self._normalize(v)
        assert chunk["text"] == "NVDA thesis text"

    def test_normalize_missing_score(self) -> None:
        """Fetch results (no score) should return score=None."""
        v = {
            "id": "MSFT:ANALYSIS:20260501-1200:risks:0",
            "metadata": {"schema_version": 1, "ticker": "MSFT", "report_type": "ANALYSIS",
                         "generated_at": "2026-05-01T12:00:00+00:00"},
        }
        chunk = self._normalize(v)
        assert chunk["score"] is None

    def test_normalize_schema_version_mismatch_raises(self) -> None:
        """Unknown schema_version must raise UnknownSchemaVersionError."""
        from src.pinecone_client import UnknownSchemaVersionError

        v = {
            "id": "AAPL:ANALYSIS:20270101-0000:intro:0",
            "score": 0.9,
            "metadata": {"schema_version": 99, "ticker": "AAPL",
                         "report_type": "ANALYSIS",
                         "generated_at": "2027-01-01T00:00:00+00:00"},
        }
        with pytest.raises(UnknownSchemaVersionError):
            self._normalize(v)

    def test_normalize_no_schema_version_passes(self) -> None:
        """Records without schema_version are allowed (legacy/partial records)."""
        v = {
            "id": "AAPL:QUICK:20260101-0000:summary:0",
            "score": 0.5,
            "metadata": {"ticker": "AAPL", "report_type": "QUICK",
                         "generated_at": "2026-01-01T00:00:00+00:00"},
        }
        chunk = self._normalize(v)
        assert chunk["id"].startswith("AAPL")

    def test_normalize_returns_required_keys(self) -> None:
        """_normalize output always has id, score, text, metadata keys."""
        v = {
            "id": "AMD:TECHNICAL:20260601-1000:overview:0",
            "score": 0.6,
            "metadata": {"schema_version": 1, "ticker": "AMD",
                         "report_type": "TECHNICAL",
                         "generated_at": "2026-06-01T10:00:00+00:00"},
        }
        chunk = self._normalize(v)
        assert set(chunk.keys()) >= {"id", "score", "text", "metadata"}


# ---------------------------------------------------------------------------
# Unit tests — retrieve post-filter logic (mocked)
# ---------------------------------------------------------------------------


class TestRetrievePostFilter:
    """
    Tests that retrieve() applies ticker/report_type post-filtering correctly
    without touching the live index.
    """

    def test_postfilter_removes_wrong_ticker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """retrieve() must drop results whose ticker doesn't match the requested one."""
        import src.pinecone_client as pc

        # Build fake query results with one matching and one non-matching record
        fake_matches = [
            {
                "id": "AAPL:ANALYSIS:20260601-1000:exec-summary:0",
                "score": 0.9,
                "metadata": {
                    "schema_version": 1,
                    "ticker": "AAPL",
                    "report_type": "ANALYSIS",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            },
            {
                "id": "MSFT:ANALYSIS:20260601-1000:exec-summary:0",
                "score": 0.85,
                "metadata": {
                    "schema_version": 1,
                    "ticker": "MSFT",
                    "report_type": "ANALYSIS",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            },
        ]

        class FakeResult:
            matches = fake_matches

        class FakeIndex:
            def query(self, **kwargs):
                return FakeResult()

        monkeypatch.setattr(pc, "_get_index", lambda: FakeIndex())
        monkeypatch.setattr(pc, "_get_namespace", lambda: "trade")

        results = pc.retrieve("what's the outlook?", ticker="AAPL")
        assert len(results) == 1
        assert results[0]["metadata"]["ticker"] == "AAPL"

    def test_postfilter_empty_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """retrieve() returns [] when there are no matches."""
        import src.pinecone_client as pc

        class FakeResult:
            matches: list = []

        class FakeIndex:
            def query(self, **kwargs):
                return FakeResult()

        monkeypatch.setattr(pc, "_get_index", lambda: FakeIndex())
        monkeypatch.setattr(pc, "_get_namespace", lambda: "trade")

        results = pc.retrieve("random query")
        assert results == []


# ---------------------------------------------------------------------------
# Live-index smoke tests — skip when key absent
# ---------------------------------------------------------------------------


@pytest.mark.live_index
class TestLiveIndex:
    """
    Smoke tests against the live trade-reports Pinecone index.

    These verify that the three retrieval primitives return the expected Python
    types and shapes when a real PINECONE_READ_KEY is set.  They do NOT assert
    specific business data (that would make the suite brittle against index changes).

    Skipped cleanly when PINECONE_READ_KEY is unset (see conftest.py).
    """

    def test_retrieve_returns_list(self) -> None:
        """retrieve() must return a list (possibly empty — index may not have AAPL)."""
        from src.pinecone_client import retrieve

        result = retrieve("bull case for AAPL", ticker="AAPL", k=3)
        assert isinstance(result, list)
        for chunk in result:
            assert "id" in chunk
            assert "score" in chunk
            assert "text" in chunk
            assert "metadata" in chunk

    def test_retrieve_without_ticker_returns_list(self) -> None:
        """retrieve() without ticker filter should also return a list."""
        from src.pinecone_client import retrieve

        result = retrieve("what are the latest trade signals?", k=3)
        assert isinstance(result, list)

    def test_latest_returns_dict_or_none(self) -> None:
        """latest() must return a dict (chunk) or None — never raise on missing ticker."""
        from src.pinecone_client import latest

        result = latest("AAPL", report_type="ANALYSIS")
        assert result is None or isinstance(result, dict)
        if result is not None:
            assert "id" in result
            assert "metadata" in result

    def test_timeline_returns_list(self) -> None:
        """timeline() must return a list (possibly empty)."""
        from src.pinecone_client import timeline

        result = timeline("AAPL", limit=5)
        assert isinstance(result, list)
        for chunk in result:
            assert "id" in chunk
            assert "metadata" in chunk

    def test_retrieve_chunk_metadata_has_required_fields(self) -> None:
        """
        Schema-contract regression (verification C from trading-chatbot.md):
        any retrieved chunk must carry the required always-present metadata fields.
        """
        from src.pinecone_client import retrieve

        results = retrieve("analyze AAPL", ticker="AAPL", k=3)
        if not results:
            pytest.skip("No results for AAPL in index — cannot verify schema fields")

        required_fields = {"ticker", "report_type", "generated_at", "source_path"}
        for chunk in results:
            missing = required_fields - set(chunk["metadata"].keys())
            assert not missing, (
                f"Chunk {chunk['id']!r} is missing required metadata fields: {missing}"
            )
