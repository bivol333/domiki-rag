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
