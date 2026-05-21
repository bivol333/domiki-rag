"""Smoke tests for migrate_to_cloud.py.

Tests argument parsing and pre-flight logic using two in-memory Qdrant instances.
Qdrant's in-memory mode (':memory:') is available in qdrant-client >= 1.7.
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_migrate():
    spec = importlib.util.spec_from_file_location(
        "migrate_to_cloud",
        Path("scripts/migrate_to_cloud.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def migrate():
    return _load_migrate()


# ---------- argument parsing ----------

class TestArgParsing:
    def test_default_collection(self, migrate):
        args = migrate.parser_args([])
        assert args.collection == "domiki_public"

    def test_custom_collection(self, migrate):
        args = migrate.parser_args(["--collection", "my_col"])
        assert args.collection == "my_col"

    def test_force_flag(self, migrate):
        args = migrate.parser_args(["--force"])
        assert args.force is True

    def test_no_force_by_default(self, migrate):
        args = migrate.parser_args([])
        assert args.force is False

    def test_resume_flag(self, migrate):
        args = migrate.parser_args(["--resume"])
        assert args.resume is True

    def test_no_resume_by_default(self, migrate):
        args = migrate.parser_args([])
        assert args.resume is False


# ---------- batch size + timeout config ----------

class TestConfig:
    def test_upsert_batch_is_fifty(self, migrate):
        assert migrate._UPSERT_BATCH == 50

    def test_cloud_timeout_is_at_least_60s(self, migrate):
        assert migrate._CLOUD_TIMEOUT_SEC >= 60

    def test_target_client_uses_increased_timeout(self, migrate):
        """_make_target_client must pass timeout=_CLOUD_TIMEOUT_SEC to QdrantClient."""
        from unittest.mock import patch as _patch
        with _patch.object(migrate, "QdrantClient") as mock_qc:
            migrate._make_target_client("https://example.qdrant.io", "key")
        mock_qc.assert_called_once()
        kwargs = mock_qc.call_args.kwargs
        assert kwargs.get("timeout") == migrate._CLOUD_TIMEOUT_SEC

    def test_max_attempts_is_five(self, migrate):
        assert migrate._UPSERT_MAX_ATTEMPTS == 5


# ---------- upsert retry logic ----------

class TestUpsertRetry:
    def test_succeeds_first_attempt(self, migrate):
        from unittest.mock import MagicMock
        target = MagicMock()
        target.upsert.return_value = None
        migrate._upsert_with_retry(
            target, "col", points=[], batch_label="points 0-9", sleep_fn=lambda _: None,
        )
        assert target.upsert.call_count == 1

    def test_retries_on_read_timeout_then_succeeds(self, migrate):
        from unittest.mock import MagicMock

        import httpx
        target = MagicMock()
        # First call raises, second succeeds
        target.upsert.side_effect = [
            httpx.ReadTimeout("read timeout"),
            None,
        ]
        sleeps = []
        migrate._upsert_with_retry(
            target, "col", points=[], batch_label="points 0-49",
            sleep_fn=lambda s: sleeps.append(s),
        )
        assert target.upsert.call_count == 2
        assert sleeps == [2.0]  # first backoff = 2 s

    def test_retries_multiple_times_then_succeeds(self, migrate):
        from unittest.mock import MagicMock

        import httpx
        target = MagicMock()
        target.upsert.side_effect = [
            httpx.ReadTimeout("timeout 1"),
            httpx.ConnectError("connect err"),
            httpx.ReadTimeout("timeout 2"),
            None,
        ]
        sleeps = []
        migrate._upsert_with_retry(
            target, "col", points=[], batch_label="points 0-49",
            sleep_fn=lambda s: sleeps.append(s),
        )
        assert target.upsert.call_count == 4
        # Backoff: 2, 4, 8
        assert sleeps == [2.0, 4.0, 8.0]

    def test_raises_after_max_attempts(self, migrate):
        from unittest.mock import MagicMock

        import httpx
        target = MagicMock()
        target.upsert.side_effect = httpx.ReadTimeout("persistent timeout")
        with pytest.raises(httpx.ReadTimeout):
            migrate._upsert_with_retry(
                target, "col", points=[], batch_label="points 0-49",
                sleep_fn=lambda _: None,
            )
        assert target.upsert.call_count == migrate._UPSERT_MAX_ATTEMPTS

    def test_non_retryable_exception_propagates_immediately(self, migrate):
        from unittest.mock import MagicMock
        target = MagicMock()
        target.upsert.side_effect = ValueError("schema error")
        with pytest.raises(ValueError):
            migrate._upsert_with_retry(
                target, "col", points=[], batch_label="points 0-49",
                sleep_fn=lambda _: None,
            )
        # No retries — failed immediately on first attempt
        assert target.upsert.call_count == 1

    def test_backoff_sequence_is_2_4_8_16_32(self, migrate):
        from unittest.mock import MagicMock

        import httpx
        target = MagicMock()
        # All 5 attempts fail → records 4 backoff sleeps
        target.upsert.side_effect = httpx.ReadTimeout("nope")
        sleeps = []
        with pytest.raises(httpx.ReadTimeout):
            migrate._upsert_with_retry(
                target, "col", points=[], batch_label="points 0-49",
                sleep_fn=lambda s: sleeps.append(s),
            )
        assert sleeps == [2.0, 4.0, 8.0, 16.0]

    def test_resumes_after_retry_qdrant_response_exception(self, migrate):
        """ResponseHandlingException from qdrant-client transport is retryable."""
        from unittest.mock import MagicMock
        target = MagicMock()
        target.upsert.side_effect = [
            migrate.ResponseHandlingException("transport error"),
            None,
        ]
        migrate._upsert_with_retry(
            target, "col", points=[], batch_label="points 0-49",
            sleep_fn=lambda _: None,
        )
        assert target.upsert.call_count == 2


# ---------- in-memory integration ----------

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )

    def _make_source_with_data() -> QdrantClient:
        client = QdrantClient(":memory:")
        client.create_collection(
            collection_name="domiki_public",
            vectors_config={"dense": VectorParams(size=4, distance=Distance.COSINE)},
            sparse_vectors_config={
                "sparse": SparseVectorParams()
            },
        )
        client.upsert(
            collection_name="domiki_public",
            points=[
                PointStruct(
                    id=1,
                    payload={"chunk_id": "abc", "text": "αυθαίρετο", "law_number": "4495/2017"},
                    vector={
                        "dense": [0.1, 0.2, 0.3, 0.4],
                        "sparse": SparseVector(indices=[10, 20], values=[1.0, 2.0]),
                    },
                ),
                PointStruct(
                    id=2,
                    payload={"chunk_id": "def", "text": "πρόστιμο", "law_number": "4495/2017"},
                    vector={
                        "dense": [0.5, 0.6, 0.7, 0.8],
                        "sparse": SparseVector(indices=[30], values=[3.0]),
                    },
                ),
            ],
        )
        return client

    _QDRANT_IN_MEMORY = True
except Exception:
    _QDRANT_IN_MEMORY = False


@pytest.mark.skipif(not _QDRANT_IN_MEMORY, reason="qdrant-client in-memory not available")
class TestInMemoryMigration:
    def test_full_migration(self, migrate):
        source = _make_source_with_data()
        target = QdrantClient(":memory:")

        migrate._recreate_collection(source, target, "domiki_public")
        assert migrate._collection_exists(target, "domiki_public")

        migrated = migrate._migrate(source, target, "domiki_public", total=2)
        assert migrated == 2
        assert migrate._point_count(target, "domiki_public") == 2

    def test_verify_passes_after_migration(self, migrate):
        source = _make_source_with_data()
        target = QdrantClient(":memory:")

        migrate._recreate_collection(source, target, "domiki_public")
        migrate._migrate(source, target, "domiki_public", total=2)

        ok = migrate._verify(source, target, "domiki_public")
        assert ok

    def test_verify_fails_on_count_mismatch(self, migrate):
        source = _make_source_with_data()
        target = QdrantClient(":memory:")

        migrate._recreate_collection(source, target, "domiki_public")
        # Migrate only 1 of 2 points by scrolling manually and upserting one
        records, _ = source.scroll("domiki_public", limit=1, with_vectors=True)
        sv = records[0].vector["sparse"]
        target.upsert(
            "domiki_public",
            points=[
                PointStruct(
                    id=records[0].id,
                    payload=records[0].payload,
                    vector={
                        "dense": records[0].vector["dense"],
                        "sparse": SparseVector(indices=sv.indices, values=sv.values),
                    },
                )
            ],
        )
        ok = migrate._verify(source, target, "domiki_public")
        assert not ok

    def test_collection_exists_helper(self, migrate):
        client = QdrantClient(":memory:")
        client.create_collection(
            "test_col", vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        assert migrate._collection_exists(client, "test_col")
        assert not migrate._collection_exists(client, "nonexistent")

    def test_point_count_helper(self, migrate):
        source = _make_source_with_data()
        assert migrate._point_count(source, "domiki_public") == 2


# ---------- pre-flight env checks ----------

class TestPreflightEnv:
    def test_missing_cloud_url_exits(self, monkeypatch, migrate, capsys):
        monkeypatch.delenv("QDRANT_CLOUD_URL", raising=False)
        monkeypatch.delenv("QDRANT_CLOUD_API_KEY", raising=False)

        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["migrate_to_cloud.py"]):
                migrate.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "QDRANT_CLOUD_URL" in captured.err

    def test_missing_api_key_exits(self, monkeypatch, migrate, capsys):
        monkeypatch.setenv("QDRANT_CLOUD_URL", "https://example.qdrant.io")
        monkeypatch.delenv("QDRANT_CLOUD_API_KEY", raising=False)

        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["migrate_to_cloud.py"]):
                migrate.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "QDRANT_CLOUD_API_KEY" in captured.err
