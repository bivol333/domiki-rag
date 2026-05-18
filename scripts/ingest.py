#!/usr/bin/env python
"""CLI: ingest PDFs into Qdrant.

Usage examples:
    uv run python scripts/ingest.py --scope public
    uv run python scripts/ingest.py --scope public --dry-run
    uv run python scripts/ingest.py --scope public --reindex
    uv run python scripts/ingest.py --scope private --path custom_subfolder
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.indexing.indexer import index_chunks
from src.indexing.qdrant_setup import ensure_collection
from src.ingestion.models import Scope
from src.ingestion.pipeline import ingest_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")


def _collection_for_scope(scope: Scope) -> str:
    return settings.public_collection if scope == "public" else settings.private_collection


def _pdf_files(scope: Scope, sub_path: str | None) -> list[Path]:
    base = Path("data/raw_pdfs") / scope
    if sub_path:
        base = base / sub_path
    return sorted(base.rglob("*.pdf"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Εισαγωγή PDF στο Qdrant")
    parser.add_argument("--scope", required=True, choices=["public", "private"])
    parser.add_argument("--path", default=None, help="Υποφάκελος εντός data/raw_pdfs/<scope>/")
    parser.add_argument(
        "--reindex", action="store_true", help="Διαγραφή και αναδημιουργία της συλλογής"
    )
    parser.add_argument("--dry-run", action="store_true", help="Ανάλυση χωρίς εγγραφή στο Qdrant")
    args = parser.parse_args()

    scope: Scope = args.scope
    collection = _collection_for_scope(scope)
    pdf_files = _pdf_files(scope, args.path)

    if not pdf_files:
        print(f"Δεν βρέθηκαν PDF αρχεία για scope='{scope}'. Έξοδος.")
        sys.exit(0)

    print(f"Βρέθηκαν {len(pdf_files)} αρχεία PDF για scope='{scope}'")

    if not args.dry_run:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
        ensure_collection(client, collection, recreate=args.reindex)
    else:
        client = None
        print("Λειτουργία dry-run: δεν θα γραφτούν δεδομένα στο Qdrant")

    t_start = time.monotonic()
    total_chunks = 0
    total_tokens = 0
    failed: list[str] = []

    for pdf_path in tqdm(pdf_files, desc="Επεξεργασία PDF", unit="αρχείο"):
        try:
            chunks = ingest_file(pdf_path, scope)
            n_chunks = len(chunks)
            n_tokens = sum(c.token_count for c in chunks)

            if not args.dry_run and chunks and client:
                index_chunks(chunks, collection, client=client)

            total_chunks += n_chunks
            total_tokens += n_tokens
            logger.info(
                "%s → %d chunks, %d tokens",
                pdf_path.name,
                n_chunks,
                n_tokens,
            )
        except Exception as exc:
            logger.error("Σφάλμα κατά την επεξεργασία %s: %s", pdf_path.name, exc)
            failed.append(pdf_path.name)

    elapsed = time.monotonic() - t_start
    cohere_cost_usd = (total_tokens / 1_000_000) * 0.10  # approx $0.10/1M tokens

    print("\n=== Αποτελέσματα εισαγωγής ===")
    print(f"  Αρχεία: {len(pdf_files)} (αποτυχία: {len(failed)})")
    print(f"  Chunks: {total_chunks}")
    print(f"  Tokens: {total_tokens:,}")
    print(f"  Χρόνος: {elapsed:.1f}s")
    if not args.dry_run:
        print(f"  Εκτιμώμενο κόστος Cohere: ~${cohere_cost_usd:.4f}")
    if failed:
        print(f"  Αποτυχημένα αρχεία: {', '.join(failed)}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
