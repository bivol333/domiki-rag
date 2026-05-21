#!/usr/bin/env python
"""CLI: ingest PDFs into Qdrant.

Usage examples:
    uv run python scripts/ingest.py --scope public
    uv run python scripts/ingest.py --scope public --dry-run
    uv run python scripts/ingest.py --scope public --reindex
    uv run python scripts/ingest.py --scope public --rebuild
    uv run python scripts/ingest.py --scope private --path custom_subfolder

Rebuild safety
--------------
--rebuild (and --reindex) use a two-phase strategy to avoid data loss:

  Phase 1 — Parse:   All PDFs are parsed into chunks (local, no network).
  Phase 2 — Embed:   All chunks are embedded via Cohere (network, no Qdrant writes).
  Phase 3 — Commit:  ONLY after every file embeds successfully does the collection get
                     wiped and new points upserted.

If any file fails to embed, the existing collection is left untouched and the script
exits with a non-zero status, listing which files failed and why.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Literal

from tqdm import tqdm

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.indexing.indexer import index_chunks, prepare_points, upsert_points
from src.indexing.qdrant_setup import ensure_collection
from src.ingestion.models import Chunk, Scope
from src.ingestion.pipeline import ingest_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")

# ── Failure reason type ───────────────────────────────────────────────────────

FailureReason = Literal[
    "parse_error", "zero_chunks", "rate_limit", "network", "upsert_error", "other"
]


def _classify_error(exc: Exception) -> FailureReason:
    """Map an exception to a human-readable failure category."""
    try:
        import cohere
        if isinstance(exc, cohere.TooManyRequestsError):
            return "rate_limit"
    except ImportError:
        pass

    exc_type = type(exc).__name__.lower()
    exc_msg = str(exc).lower()
    if any(kw in exc_type for kw in ("connect", "timeout", "network", "socket")):
        return "network"
    if any(kw in exc_msg for kw in ("connection", "timeout", "network", "socket", "ssl")):
        return "network"
    # RuntimeError wrapping from embedder preserves original message
    if isinstance(exc, RuntimeError) and "rate" in exc_msg:
        return "rate_limit"
    return "other"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collection_for_scope(scope: Scope) -> str:
    return settings.public_collection if scope == "public" else settings.private_collection


def _pdf_files(scope: Scope, sub_path: str | None) -> list[Path]:
    base = Path("data/raw_pdfs") / scope
    if sub_path:
        base = base / sub_path
    return sorted(base.rglob("*.pdf"))


def _print_rebuild_warning(collection: str, n_files: int) -> None:
    print()
    print("!" * 60)
    print(f"  ΠΡΟΕΙΔΟΠΟΙΗΣΗ: Η συλλογή '{collection}' θα ΔΙΑΓΡΑΦΕΙ")
    print(f"  και θα ξανα-εισαχθούν {n_files} αρχεία PDF από την αρχή.")
    print("  Η διαγραφή γίνεται ΜΟΝΟ αφού ολοκληρωθεί επιτυχώς")
    print("  η ενσωμάτωση ΟΛΩΝ των αρχείων.")
    print("!" * 60)
    print()


# ── Two-phase rebuild ─────────────────────────────────────────────────────────

def run_rebuild(
    pdf_files: list[Path],
    scope: Scope,
    collection: str,
    client: object,  # QdrantClient — typed loosely to avoid import at module level
) -> tuple[int, int, dict[str, FailureReason]]:
    """Parse → embed ALL files → only then wipe collection and upsert.

    Returns (total_chunks, total_tokens, failed_reasons).
    If any file fails to embed, the collection is NOT modified.
    """
    from qdrant_client.models import PointStruct

    failed: dict[str, FailureReason] = {}

    # ── Phase 1: Parse (local, no network) ───────────────────────────────────
    print("Φάση 1/3 — Ανάλυση PDF (τοπικά, χωρίς δίκτυο)...")
    parsed: dict[Path, list[Chunk]] = {}
    for pdf_path in tqdm(pdf_files, desc="Parsing", unit="file"):
        try:
            chunks = ingest_file(pdf_path, scope)
            parsed[pdf_path] = chunks
            if not chunks:
                logger.warning("%s → 0 chunks (αρχείο εισόδου χωρίς περιεχόμενο)", pdf_path.name)
        except Exception as exc:
            logger.error("Parse error %s: %s", pdf_path.name, exc)
            failed[pdf_path.name] = "parse_error"

    # ── Phase 2: Embed (network, no Qdrant writes) ────────────────────────────
    print("Φάση 2/3 — Ενσωμάτωση (Cohere, χωρίς εγγραφή στο Qdrant)...")
    all_points: dict[Path, list[PointStruct]] = {}
    embed_failed: list[str] = []

    for pdf_path, chunks in tqdm(
        [(p, c) for p, c in parsed.items() if p.name not in failed],
        desc="Embedding",
        unit="file",
    ):
        if not chunks:
            continue  # zero-chunk files skipped silently (they'll have 0 points)
        try:
            points = prepare_points(chunks, source_hint=pdf_path.name)
            all_points[pdf_path] = points
            logger.info("%s → %d points prepared", pdf_path.name, len(points))
        except Exception as exc:
            reason = _classify_error(exc)
            logger.error("Embedding failed for %s (%s): %s", pdf_path.name, reason, exc)
            failed[pdf_path.name] = reason
            embed_failed.append(pdf_path.name)

    # ── Abort if any embedding failed ─────────────────────────────────────────
    if embed_failed:
        print()
        print("=" * 60)
        print(f"  ΑΠΟΤΥΧΙΑ: Η ενσωμάτωση απέτυχε για {len(embed_failed)} αρχεία.")
        print("  Η συλλογή ΔΕΝ τροποποιήθηκε — τα υπάρχοντα δεδομένα παραμένουν άθικτα.")
        print("  Αποτυχημένα αρχεία:")
        for fname in embed_failed:
            print(f"    - {fname}: {failed[fname]}")
        print("=" * 60)
        return 0, 0, failed

    # ── Phase 3: Wipe collection, then upsert ────────────────────────────────
    print("Φάση 3/3 — Διαγραφή συλλογής και εισαγωγή νέων δεδομένων...")
    logger.warning("Dropping collection '%s' — all previous data will be lost", collection)
    ensure_collection(client, collection, recreate=True)

    total_chunks = 0
    total_tokens = 0
    for pdf_path in tqdm(
        [p for p in pdf_files if p in all_points],
        desc="Upserting",
        unit="file",
    ):
        points = all_points[pdf_path]
        try:
            upsert_points(points, collection, client)
            n_chunks = len(points)
            n_tokens = sum(c.token_count for c in parsed[pdf_path])
            total_chunks += n_chunks
            total_tokens += n_tokens
            logger.info("%s → %d chunks upserted", pdf_path.name, n_chunks)
        except Exception as exc:
            logger.error("Upsert failed for %s: %s", pdf_path.name, exc)
            failed[pdf_path.name] = "upsert_error"

    return total_chunks, total_tokens, failed


# ── Incremental run (normal, no collection wipe) ──────────────────────────────

def run_incremental(
    pdf_files: list[Path],
    scope: Scope,
    collection: str,
    client: object | None,
    dry_run: bool,
) -> tuple[int, int, dict[str, FailureReason]]:
    """Process files one by one, upserting as we go.  No collection wipe."""
    failed: dict[str, FailureReason] = {}
    total_chunks = 0
    total_tokens = 0

    for pdf_path in tqdm(pdf_files, desc="Επεξεργασία PDF", unit="αρχείο"):
        try:
            chunks = ingest_file(pdf_path, scope)
        except Exception as exc:
            logger.error("Parse error %s: %s", pdf_path.name, exc)
            failed[pdf_path.name] = "parse_error"
            continue

        n_chunks = len(chunks)
        n_tokens = sum(c.token_count for c in chunks)

        if not dry_run and chunks and client:
            try:
                index_chunks(chunks, collection, client=client, source_hint=pdf_path.name)
            except Exception as exc:
                reason = _classify_error(exc)
                logger.error("Index error %s (%s): %s", pdf_path.name, reason, exc)
                failed[pdf_path.name] = reason
                continue

        total_chunks += n_chunks
        total_tokens += n_tokens
        logger.info("%s → %d chunks, %d tokens", pdf_path.name, n_chunks, n_tokens)

    return total_chunks, total_tokens, failed


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Εισαγωγή PDF στο Qdrant")
    parser.add_argument("--scope", required=True, choices=["public", "private"])
    parser.add_argument("--path", default=None, help="Υποφάκελος εντός data/raw_pdfs/<scope>/")
    parser.add_argument(
        "--reindex", action="store_true", help="Διαγραφή και αναδημιουργία της συλλογής"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Πλήρης επανεισαγωγή από μηδέν. Η συλλογή διαγράφεται ΜΟΝΟ αφού "
            "επιτύχει η ενσωμάτωση ΟΛΩΝ των αρχείων (ασφαλής από μερική αποτυχία)."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Ανάλυση χωρίς εγγραφή στο Qdrant")
    args = parser.parse_args()

    scope: Scope = args.scope
    collection = _collection_for_scope(scope)
    pdf_files = _pdf_files(scope, args.path)
    rebuild = args.reindex or args.rebuild

    if not pdf_files:
        print(f"Δεν βρέθηκαν PDF αρχεία για scope='{scope}'. Έξοδος.")
        sys.exit(0)

    print(f"Βρέθηκαν {len(pdf_files)} αρχεία PDF για scope='{scope}'")

    if rebuild and not args.dry_run:
        _print_rebuild_warning(collection, len(pdf_files))

    if args.dry_run:
        print("Λειτουργία dry-run: δεν θα γραφτούν δεδομένα στο Qdrant")
        client = None
    else:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)

    t_start = time.monotonic()

    if rebuild and not args.dry_run:
        total_chunks, total_tokens, failed = run_rebuild(pdf_files, scope, collection, client)
    else:
        if not args.dry_run:
            ensure_collection(client, collection, recreate=False)
        total_chunks, total_tokens, failed = run_incremental(
            pdf_files, scope, collection, client, dry_run=args.dry_run
        )

    elapsed = time.monotonic() - t_start
    cohere_cost_usd = (total_tokens / 1_000_000) * 0.10  # approx $0.10/1M tokens

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n=== Αποτελέσματα εισαγωγής ===")
    print(f"  Αρχεία: {len(pdf_files)} (αποτυχία: {len(failed)})")
    print(f"  Chunks: {total_chunks}")
    print(f"  Tokens: {total_tokens:,}")
    print(f"  Χρόνος: {elapsed:.1f}s")
    if not args.dry_run:
        print(f"  Εκτιμώμενο κόστος Cohere: ~${cohere_cost_usd:.4f}")
    if failed:
        print("  Αποτυχημένα αρχεία:")
        for fname, reason in failed.items():
            print(f"    - {fname}: {reason}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
