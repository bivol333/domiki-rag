"""Tests for two-phase rebuild atomicity in scripts/ingest.py.

The core invariant: `ensure_collection(recreate=True)` — which wipes the collection —
must NEVER be called if any file's embedding fails.  Pre-existing data must survive.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make the project root importable (mirrors how ingest.py itself sets up sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cohere

from scripts.ingest import _classify_error, run_rebuild
from src.ingestion.models import Chunk, DocumentMetadata, Scope

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _rate_limit_exc() -> cohere.TooManyRequestsError:
    return cohere.TooManyRequestsError(body="rate limit exceeded")


def _make_chunk(source_file: str, text: str = "Κείμενο άρθρου.") -> Chunk:
    doc = DocumentMetadata(
        source_file=source_file,
        scope="public",
        source_type="law",
        total_pages=1,
    )
    return Chunk(
        chunk_id="deadbeef" * 2,  # 16-char hex placeholder
        document=doc,
        text=text,
        page_start=1,
        page_end=1,
        char_count=len(text),
        token_count=len(text.split()),
    )


def _mock_client() -> MagicMock:
    """Return a mock QdrantClient that records calls."""
    client = MagicMock()
    return client


def _fake_pdf_files(names: list[str], tmp_path: Path) -> list[Path]:
    """Create empty placeholder PDF files in tmp_path and return their paths."""
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(b"%PDF-1.4 placeholder")
        paths.append(p)
    return sorted(paths)


# ── Atomicity tests ───────────────────────────────────────────────────────────

class TestRebuildAtomicity:
    """ensure_collection(recreate=True) must not be called when embedding fails."""

    def test_collection_not_wiped_on_embedding_failure(self, tmp_path):
        """If one file's embedding raises, delete_collection must NOT be called."""
        pdf_files = _fake_pdf_files(["law_a.pdf", "law_b.pdf"], tmp_path)
        chunks_a = [_make_chunk("law_a.pdf", f"Άρθρο {i} κείμενο.") for i in range(3)]
        chunks_b = [_make_chunk("law_b.pdf", f"Άρθρο {i} κείμενο.") for i in range(3)]
        client = _mock_client()

        def fake_ingest(path: Path, scope: Scope) -> list[Chunk]:
            return chunks_a if "law_a" in path.name else chunks_b

        def fake_prepare(chunks, source_hint=""):
            if "law_b" in source_hint:
                raise _rate_limit_exc()
            # Return dummy PointStructs for law_a
            return [MagicMock() for _ in chunks]

        with (
            patch("scripts.ingest.ingest_file", side_effect=fake_ingest),
            patch("scripts.ingest.prepare_points", side_effect=fake_prepare),
            patch("scripts.ingest.ensure_collection") as mock_ensure,
        ):
            total_chunks, total_tokens, failed = run_rebuild(
                pdf_files, "public", "domiki_public", client
            )

        # Collection must NOT have been wiped
        mock_ensure.assert_not_called()
        client.delete_collection.assert_not_called()

        # law_b must appear in failures
        assert "law_b.pdf" in failed
        assert failed["law_b.pdf"] == "rate_limit"
        # No chunks should have been upserted
        assert total_chunks == 0

    def test_collection_wiped_only_after_all_succeed(self, tmp_path):
        """When all files embed successfully, collection IS wiped exactly once."""
        pdf_files = _fake_pdf_files(["law_a.pdf", "law_b.pdf"], tmp_path)
        chunks = [_make_chunk("law_a.pdf")]
        client = _mock_client()

        dummy_points = [MagicMock()]

        with (
            patch("scripts.ingest.ingest_file", return_value=chunks),
            patch("scripts.ingest.prepare_points", return_value=dummy_points),
            patch("scripts.ingest.upsert_points"),
            patch("scripts.ingest.ensure_collection") as mock_ensure,
        ):
            total_chunks, total_tokens, failed = run_rebuild(
                pdf_files, "public", "domiki_public", client
            )

        assert not failed
        # ensure_collection called exactly once, with recreate=True
        mock_ensure.assert_called_once_with(client, "domiki_public", recreate=True)

    def test_partial_embedding_failure_preserves_collection(self, tmp_path):
        """3 files: file 2 fails.  Collection must remain untouched."""
        pdf_files = _fake_pdf_files(["a.pdf", "b.pdf", "c.pdf"], tmp_path)
        client = _mock_client()

        def fake_ingest(path, scope):
            return [_make_chunk(path.name)]

        call_count = {"n": 0}

        def fake_prepare(chunks, source_hint=""):
            call_count["n"] += 1
            if "b.pdf" in source_hint:
                raise RuntimeError("Simulated network error")
            return [MagicMock()]

        with (
            patch("scripts.ingest.ingest_file", side_effect=fake_ingest),
            patch("scripts.ingest.prepare_points", side_effect=fake_prepare),
            patch("scripts.ingest.ensure_collection") as mock_ensure,
        ):
            _, _, failed = run_rebuild(pdf_files, "public", "domiki_public", client)

        mock_ensure.assert_not_called()
        assert "b.pdf" in failed
        # a and c were attempted (prepare_points called for them)
        assert call_count["n"] >= 2

    def test_parse_failure_does_not_prevent_successful_embed_and_wipe(self, tmp_path):
        """A parse error on one file must not block others — wipe still happens
        if the remaining files all embed successfully."""
        pdf_files = _fake_pdf_files(["bad.pdf", "good.pdf"], tmp_path)
        client = _mock_client()
        good_chunks = [_make_chunk("good.pdf")]

        def fake_ingest(path, scope):
            if "bad" in path.name:
                raise RuntimeError("Corrupt PDF")
            return good_chunks

        with (
            patch("scripts.ingest.ingest_file", side_effect=fake_ingest),
            patch("scripts.ingest.prepare_points", return_value=[MagicMock()]),
            patch("scripts.ingest.upsert_points"),
            patch("scripts.ingest.ensure_collection") as mock_ensure,
        ):
            _, _, failed = run_rebuild(pdf_files, "public", "domiki_public", client)

        # Parse error is recorded
        assert "bad.pdf" in failed
        assert failed["bad.pdf"] == "parse_error"
        # But good.pdf embedded OK, so collection IS wiped (only parse failed, not embed)
        mock_ensure.assert_called_once_with(client, "domiki_public", recreate=True)


# ── Error classification tests ────────────────────────────────────────────────

class TestClassifyError:
    def test_too_many_requests_is_rate_limit(self):
        assert _classify_error(_rate_limit_exc()) == "rate_limit"

    def test_connect_error_is_network(self):
        class FakeConnectError(ConnectionError):
            pass
        assert _classify_error(FakeConnectError("refused")) == "network"

    def test_timeout_error_is_network(self):
        class FakeTimeout(TimeoutError):
            pass
        assert _classify_error(FakeTimeout("timed out")) == "network"

    def test_network_keyword_in_message_is_network(self):
        assert _classify_error(RuntimeError("network unreachable")) == "network"

    def test_generic_runtime_error_is_other(self):
        assert _classify_error(RuntimeError("unexpected server error")) == "other"

    def test_value_error_is_other(self):
        assert _classify_error(ValueError("bad data")) == "other"
