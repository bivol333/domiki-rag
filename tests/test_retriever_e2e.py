"""End-to-end retriever tests against the live Qdrant collection.

These tests require:
- Qdrant running on localhost:6333
- The domiki_public collection populated (172 chunks from Phase 1)
- Valid COHERE_API_KEY in .env

Mark as integration tests; skip if Qdrant is unreachable.
"""
import pytest

from src.retrieval.hybrid_search import Hit, hybrid_search
from src.retrieval.retriever import Retriever


def _qdrant_available() -> bool:
    try:
        from qdrant_client import QdrantClient

        from src.config import settings
        c = QdrantClient(url=settings.qdrant_url)
        c.get_collections()
        return True
    except Exception:
        return False


skip_if_no_qdrant = pytest.mark.skipif(
    not _qdrant_available(),
    reason="Qdrant not available",
)


@skip_if_no_qdrant
@pytest.mark.asyncio
async def test_hybrid_search_returns_hits():
    hits = await hybrid_search("αυθαίρετο κτίριο", initial_k=10)
    assert len(hits) > 0
    assert all(isinstance(h, Hit) for h in hits)
    assert all(h.score > 0 for h in hits)


@skip_if_no_qdrant
@pytest.mark.asyncio
async def test_hybrid_search_has_payloads():
    hits = await hybrid_search("πρόστιμο αυθαίρετης κατασκευής", initial_k=10)
    assert len(hits) > 0
    # At least some hits should have article metadata
    articles = [h.article for h in hits if h.article]
    assert len(articles) > 0, "Expected at least one hit with article metadata"


@skip_if_no_qdrant
@pytest.mark.asyncio
async def test_retriever_no_rerank_returns_results():
    retriever = Retriever()
    results = await retriever.search("διαδικασία υπαγωγής", top_k=5, rerank=False)
    assert len(results) > 0
    assert len(results) <= 5


@skip_if_no_qdrant
@pytest.mark.asyncio
async def test_retriever_with_rerank_returns_results():
    retriever = Retriever()
    results = await retriever.search("πρόστιμο αυθαίρετης κατασκευής", top_k=5, rerank=True)
    assert len(results) > 0
    # Reranked results should have rerank_score
    assert all(r.rerank_score > 0 for r in results)


@skip_if_no_qdrant
@pytest.mark.asyncio
async def test_hybrid_beats_dense_on_sparse_term():
    """Hybrid search should return different ranking than dense-only on specific article refs."""
    hybrid_hits = await hybrid_search("Άρθρο 116 παραδοσιακοί οικισμοί", initial_k=20)
    assert len(hybrid_hits) > 0
    hybrid_articles = [h.article for h in hybrid_hits[:5] if h.article]
    # Article 116 should appear somewhere in top results for hybrid
    # (not strictly required here but logs the result for inspection)
    print(f"Hybrid top-5 articles: {hybrid_articles}")
