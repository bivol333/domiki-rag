"""Copy a local Qdrant collection to a cloud Qdrant cluster.

Usage:
    uv run python scripts/migrate_to_cloud.py [--force] [--collection NAME]

Reads QDRANT_CLOUD_URL and QDRANT_CLOUD_API_KEY from .env or environment.
Source is the local Qdrant instance from settings.qdrant_url (read-only).
"""
import argparse
import os
import random
import sys
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    OptimizersConfigDiff,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from tqdm import tqdm

load_dotenv()

_DEFAULT_COLLECTION = "domiki_public"
_SCROLL_BATCH = 100


def parser_args(argv: list[str] | None = None):
    """Parse CLI arguments. Exposed for testing."""
    parser = argparse.ArgumentParser(
        description="Migrate a local Qdrant collection to the cloud.",
    )
    parser.add_argument(
        "--collection", default=_DEFAULT_COLLECTION, help="Collection name to migrate",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite non-empty target collection (use with caution)",
    )
    return parser.parse_args(argv)


# ---------- helpers ----------

def _make_source_client() -> QdrantClient:
    from src.config import settings
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


def _make_target_client(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key)


def _check_reachable(client: QdrantClient, label: str) -> None:
    try:
        client.get_collections()
    except Exception as exc:
        print(f"ERROR: Cannot reach {label}: {exc}", file=sys.stderr)
        sys.exit(1)


def _collection_exists(client: QdrantClient, name: str) -> bool:
    return any(c.name == name for c in client.get_collections().collections)


def _point_count(client: QdrantClient, name: str) -> int:
    return client.count(name).count


# ---------- collection creation ----------

def _recreate_collection(
    source: QdrantClient,
    target: QdrantClient,
    collection: str,
) -> None:
    info = source.get_collection(collection)
    params = info.config.params
    oc = info.config.optimizer_config

    # Extract named vectors (there is only "dense" in our schema)
    vectors_config: dict[str, VectorParams] = {}
    for name, vp in params.vectors.items():
        vectors_config[name] = VectorParams(
            size=vp.size,
            distance=vp.distance,
            hnsw_config=vp.hnsw_config,
            on_disk=vp.on_disk,
        )

    # Extract sparse vectors (there is only "sparse")
    sparse_vectors_config: dict[str, SparseVectorParams] = {}
    for name, svp in (params.sparse_vectors or {}).items():
        sparse_vectors_config[name] = SparseVectorParams(
            index=svp.index,
            modifier=svp.modifier,
        )

    optimizers_config = OptimizersConfigDiff(
        deleted_threshold=oc.deleted_threshold,
        vacuum_min_vector_number=oc.vacuum_min_vector_number,
        default_segment_number=oc.default_segment_number,
        max_segment_size=oc.max_segment_size,
        memmap_threshold=oc.memmap_threshold,
        indexing_threshold=oc.indexing_threshold,
        flush_interval_sec=oc.flush_interval_sec,
        max_optimization_threads=oc.max_optimization_threads,
    )

    target.create_collection(
        collection_name=collection,
        vectors_config=vectors_config,
        sparse_vectors_config=sparse_vectors_config or None,
        shard_number=params.shard_number,
        replication_factor=params.replication_factor,
        on_disk_payload=params.on_disk_payload,
        optimizers_config=optimizers_config,
    )
    print(f"  Created collection '{collection}' on target.")


# ---------- migration ----------

def _migrate(
    source: QdrantClient,
    target: QdrantClient,
    collection: str,
    total: int,
) -> int:
    migrated = 0
    offset = None

    with tqdm(total=total, unit="pt", desc="Migrating") as bar:
        while True:
            records, next_offset = source.scroll(
                collection_name=collection,
                limit=_SCROLL_BATCH,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )
            if not records:
                break

            points: list[PointStruct] = []
            for rec in records:
                vec = rec.vector
                dense = vec["dense"]
                sv = vec["sparse"]
                points.append(
                    PointStruct(
                        id=rec.id,
                        payload=rec.payload,
                        vector={
                            "dense": dense,
                            "sparse": SparseVector(
                                indices=sv.indices,
                                values=sv.values,
                            ),
                        },
                    )
                )

            target.upsert(collection_name=collection, points=points)
            migrated += len(points)
            bar.update(len(points))

            if next_offset is None:
                break
            offset = next_offset

    return migrated


# ---------- verification ----------

def _verify(
    source: QdrantClient,
    target: QdrantClient,
    collection: str,
) -> bool:
    src_count = _point_count(source, collection)
    tgt_count = _point_count(target, collection)
    print("\nVerification:")
    print(f"  Source points : {src_count}")
    print(f"  Target points : {tgt_count}")

    if src_count != tgt_count:
        print("  FAIL: point counts differ!", file=sys.stderr)
        return False
    print("  Point counts match. ✓")

    # Spot-check one random point
    src_records, _ = source.scroll(
        collection, limit=src_count, with_vectors=True, with_payload=True,
    )
    sample = random.choice(src_records)
    tgt_results = target.retrieve(
        collection_name=collection,
        ids=[sample.id],
        with_vectors=True,
        with_payload=True,
    )
    if not tgt_results:
        print(f"  FAIL: point {sample.id} not found on target!", file=sys.stderr)
        return False

    tgt_pt = tgt_results[0]
    src_dense_len = len(sample.vector["dense"])
    tgt_dense_len = len(tgt_pt.vector["dense"])
    src_payload_keys = set(sample.payload.keys())
    tgt_payload_keys = set(tgt_pt.payload.keys())

    if src_dense_len != tgt_dense_len:
        print(
            f"  FAIL: dense vector length mismatch ({src_dense_len} vs {tgt_dense_len})",
            file=sys.stderr,
        )
        return False
    if src_payload_keys != tgt_payload_keys:
        diff = src_payload_keys ^ tgt_payload_keys
        print(f"  FAIL: payload key mismatch: {diff}", file=sys.stderr)
        return False

    print(f"  Spot-check point {sample.id}: dense[{src_dense_len}d], payload keys match. ✓")
    return True


# ---------- main ----------

def main() -> None:
    args = parser_args()
    collection = args.collection

    # Resolve target credentials
    cloud_url = os.getenv("QDRANT_CLOUD_URL", "").strip()
    cloud_api_key = os.getenv("QDRANT_CLOUD_API_KEY", "").strip()
    if not cloud_url or not cloud_api_key:
        print(
            "ERROR: QDRANT_CLOUD_URL and QDRANT_CLOUD_API_KEY must be set in .env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Migration: '{collection}'  local → cloud")
    print("  Source: local Qdrant")
    print(f"  Target: {cloud_url}")

    # --- Pre-flight checks ---
    print("\n[1/5] Pre-flight checks...")
    source = _make_source_client()
    target = _make_target_client(cloud_url, cloud_api_key)

    _check_reachable(source, "local Qdrant")
    print("  Local Qdrant reachable. ✓")
    _check_reachable(target, "cloud Qdrant")
    print("  Cloud Qdrant reachable. ✓")

    if not _collection_exists(source, collection):
        print(f"ERROR: Collection '{collection}' not found on local Qdrant.", file=sys.stderr)
        sys.exit(1)

    src_count = _point_count(source, collection)
    if src_count == 0:
        print(
            f"ERROR: Collection '{collection}' is empty locally — nothing to migrate.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  Source collection '{collection}': {src_count} points. ✓")

    if _collection_exists(target, collection):
        tgt_count = _point_count(target, collection)
        if tgt_count > 0 and not args.force:
            print(
                f"ERROR: Target collection '{collection}' already has {tgt_count} points.\n"
                "       Pass --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(1)
        if tgt_count > 0:
            print(f"  WARNING: target has {tgt_count} existing points — overwriting (--force).")
        target.delete_collection(collection)
        print(f"  Deleted existing target collection '{collection}'.")

    # --- Replicate collection config ---
    print("\n[2/5] Replicating collection config...")
    _recreate_collection(source, target, collection)

    # --- Stream points ---
    print(f"\n[3/5] Streaming {src_count} points in batches of {_SCROLL_BATCH}...")
    t0 = time.monotonic()
    migrated = _migrate(source, target, collection, total=src_count)
    elapsed = time.monotonic() - t0
    rate = migrated / max(elapsed, 0.001)
    print(f"  Migrated {migrated} points in {elapsed:.1f}s ({rate:.0f} pt/s).")

    # --- Verify ---
    print("\n[4/5] Post-migration verification...")
    ok = _verify(source, target, collection)

    # --- Summary ---
    print("\n[5/5] Summary")
    print(f"  Collection  : {collection}")
    print(f"  Points      : {migrated}")
    print(f"  Duration    : {elapsed:.1f}s")
    info = source.get_collection(collection)
    for vname, vp in info.config.params.vectors.items():
        print(f"  Vector '{vname}': {vp.size}d {vp.distance.value}")
    for vname in (info.config.params.sparse_vectors or {}):
        print(f"  Sparse '{vname}': BM25")

    if not ok:
        print(
            "\nERROR: Verification failed. Target collection may be partial.\n"
            "To delete partial target: qdrant-client or run this script with --force again.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("\nMigration complete. ✓")


if __name__ == "__main__":
    main()
