"""Diagnostic: trace a query through every retrieval stage.

For one query (or several), runs each retrieval mode independently and marks
which results come from a given target file (default: PD-24-1985).

Stages:
    1. Dense-only top 20 (Cohere embed → Qdrant ANN)
    2. Sparse-only top 20 (BM25 → Qdrant sparse search)
    3. Hybrid RRF fusion top 20 (current production pipeline)
    4. Cohere rerank → final top 8

Also prints a corpus-level inspection of all chunks for the target file:
chunk count, sample texts, metadata.

Usage:
    uv run python scripts/diagnose_retrieval.py
"""
import asyncio
import sys
from pathlib import Path

# Force UTF-8 console so Greek text doesn't render as mojibake on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except AttributeError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import AsyncQdrantClient, QdrantClient

from src.common.tokenizer import text_to_sparse
from src.config import settings
from src.indexing.embedder import embed_chunks
from src.retrieval.hybrid_search import Hit, _payload_to_hit, hybrid_search
from src.retrieval.reranker import rerank as do_rerank

TARGET_FILE = "PD-24-1985-Ektos-Sxediou.pdf"
COLLECTION = "domiki_public"

QUERIES = [
    "Τι ισχύει για δόμηση εκτός σχεδίου σε αγροτεμάχιο;",
    "δόμηση εκτός σχεδίου",
    "όροι δόμησης εκτός σχεδίου πόλεως αγροτεμάχιο",
    "π.δ. 24/1985 εκτός σχεδίου",
]


# ────────────────────────────────────────────────────────────────────────────
# Stage runners
# ────────────────────────────────────────────────────────────────────────────

async def _dense_only(client: AsyncQdrantClient, query: str, k: int) -> list[Hit]:
    """Pure dense vector search — no sparse, no fusion."""

    dense_vec = embed_chunks([query], input_type="search_query")[0]
    response = await client.query_points(
        collection_name=COLLECTION,
        query=dense_vec,
        using="dense",
        limit=k,
        with_payload=True,
    )
    return [_payload_to_hit(int(p.id), p.score, p.payload) for p in response.points]


async def _sparse_only(client: AsyncQdrantClient, query: str, k: int) -> list[Hit]:
    """Pure BM25 sparse search — no dense, no fusion."""
    from qdrant_client.models import SparseVector

    sparse_dict = text_to_sparse(query)
    indices = list(sparse_dict.keys())
    values = [sparse_dict[i] for i in indices]
    if not indices:
        return []
    sparse_vec = SparseVector(indices=indices, values=values)

    response = await client.query_points(
        collection_name=COLLECTION,
        query=sparse_vec,
        using="sparse",
        limit=k,
        with_payload=True,
    )
    return [_payload_to_hit(int(p.id), p.score, p.payload) for p in response.points]


# ────────────────────────────────────────────────────────────────────────────
# Pretty printing
# ────────────────────────────────────────────────────────────────────────────

def _mark(source_file: str | None) -> str:
    return " ★ TARGET" if source_file == TARGET_FILE else ""


def _print_hits(stage_name: str, hits: list[Hit], top_n: int = 20) -> int:
    """Print the top-N hits and return how many came from TARGET_FILE."""
    print(f"\n── {stage_name} (top {min(top_n, len(hits))} of {len(hits)}) ──")
    pd24_count = sum(1 for h in hits[:top_n] if h.source_file == TARGET_FILE)
    print(f"  PD-24 chunks in this stage: {pd24_count}")
    for i, h in enumerate(hits[:top_n], 1):
        src = (h.source_file or "?")[:42]
        art = h.article or "—"
        law = h.law_number or "—"
        snippet = (h.text or "").replace("\n", " ").strip()[:90]
        print(
            f"  {i:2}. {h.score:7.4f} | {src:42} | art={art:10} | "
            f"law={law:14} {_mark(h.source_file)}"
        )
        print(f"      {snippet}")
    return pd24_count


def _print_ranked(stage_name: str, ranked, top_n: int = 8) -> int:
    """Print reranked output."""
    print(f"\n── {stage_name} (top {min(top_n, len(ranked))}) ──")
    pd24_count = sum(1 for r in ranked[:top_n] if r.hit.source_file == TARGET_FILE)
    print(f"  PD-24 chunks in final top-{top_n}: {pd24_count}")
    for r in ranked[:top_n]:
        h = r.hit
        src = (h.source_file or "?")[:42]
        art = h.article or "—"
        snippet = (h.text or "").replace("\n", " ").strip()[:90]
        print(
            f"  {r.rerank_rank:2}. rerank={r.rerank_score:7.4f} fused={r.fused_score:6.3f} "
            f"| {src:42} | art={art:10}{_mark(h.source_file)}"
        )
        print(f"      {snippet}")
    return pd24_count


# ────────────────────────────────────────────────────────────────────────────
# Corpus inspection
# ────────────────────────────────────────────────────────────────────────────

def _inspect_target_chunks() -> None:
    """Dump all chunks for TARGET_FILE so we can see what's actually indexed."""
    print(f"\n{'=' * 78}")
    print(f"CORPUS INSPECTION: {TARGET_FILE}")
    print("=" * 78)
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    flt = Filter(must=[FieldCondition(key="source_file", match=MatchValue(value=TARGET_FILE))])

    all_recs = []
    offset = None
    while True:
        recs, next_off = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=flt,
            limit=200,
            offset=offset,
            with_payload=True,
        )
        all_recs.extend(recs)
        if next_off is None:
            break
        offset = next_off

    print(f"  Total chunks: {len(all_recs)}")
    if not all_recs:
        print("  ⚠ NO CHUNKS FOUND for this file in the collection!")
        return

    # Aggregate metadata
    laws = {r.payload.get("law_number") for r in all_recs}
    types = {r.payload.get("source_type") for r in all_recs}
    articles = [r.payload.get("article") for r in all_recs]
    n_no_article = sum(1 for a in articles if a is None)
    n_with_article = len(articles) - n_no_article

    print(f"  law_number values: {laws}")
    print(f"  source_type values: {types}")
    print(f"  chunks with article: {n_with_article}  /  without: {n_no_article}")
    sample_articles = sorted({a for a in articles if a})
    suffix = "..." if len(sample_articles) > 10 else ""
    print(f"  distinct articles: {sample_articles[:10]}{suffix}")

    # Show 3 sample chunks
    print("\n  Sample chunks (first 300 chars):")
    for i, rec in enumerate(all_recs[:3], 1):
        p = rec.payload
        text = (p.get("text") or "").replace("\n", " ").strip()
        print(
            f"\n  [{i}] page {p.get('page_start')}-{p.get('page_end')}, "
            f"article={p.get('article')}"
        )
        print(f"      char_count={p.get('char_count')}, token_count={p.get('token_count')}")
        print(f"      text: {text[:300]}")


# ────────────────────────────────────────────────────────────────────────────
# Per-query trace
# ────────────────────────────────────────────────────────────────────────────

async def _trace_query(query: str) -> None:
    print(f"\n{'=' * 78}")
    print(f"QUERY: {query}")
    print("=" * 78)

    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )
    try:
        # 1. Dense-only
        dense_hits = await _dense_only(client, query, k=20)
        n_dense = _print_hits("STAGE 1: Dense-only (Cohere embed)", dense_hits)

        # 2. Sparse-only
        sparse_hits = await _sparse_only(client, query, k=20)
        n_sparse = _print_hits("STAGE 2: Sparse-only (BM25)", sparse_hits)

        # 3. Hybrid RRF (production)
        hybrid_hits = await hybrid_search(
            query=query, collection=COLLECTION, initial_k=50, client=client
        )
        n_hybrid = _print_hits("STAGE 3: Hybrid RRF fusion (initial_k=50)", hybrid_hits, top_n=20)

        # 4. Rerank → top 8
        ranked = await do_rerank(query=query, hits=hybrid_hits, top_k=8)
        n_final = _print_ranked("STAGE 4: Cohere rerank → final top-8", ranked, top_n=8)
    finally:
        await client.close()

    # Summary
    print("\n── PD-24 funnel for this query ──")
    print(f"   Dense-only top-20:   {n_dense}")
    print(f"   Sparse-only top-20:  {n_sparse}")
    print(f"   Hybrid RRF top-20:   {n_hybrid}")
    print(f"   After rerank top-8:  {n_final}")


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"Diagnostic on Qdrant {settings.qdrant_url}, collection '{COLLECTION}'")
    _inspect_target_chunks()
    for q in QUERIES:
        await _trace_query(q)
    print("\n" + "=" * 78)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
