"""Main retrieval interface: query → ranked chunks with citations."""
import logging
import time

from src.config import settings
from src.retrieval.hybrid_search import Hit, hybrid_search
from src.retrieval.query_processor import process_query
from src.retrieval.reranker import RankedHit
from src.retrieval.reranker import rerank as do_rerank

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(
        self,
        collection: str = settings.public_collection,
    ) -> None:
        self._collection = collection

    async def search(
        self,
        query: str,
        top_k: int = 10,
        initial_k: int = 50,
        rerank: bool = True,
    ) -> list[RankedHit]:
        t0 = time.perf_counter()

        processed = process_query(query)
        logger.info(
            "query_processor: articles=%s laws=%s keywords=%s",
            processed.detected_articles,
            processed.detected_law_refs,
            processed.keywords[:10],
        )

        hits: list[Hit] = await hybrid_search(
            query=processed.normalized,
            collection=self._collection,
            initial_k=initial_k,
            article_filter=processed.detected_articles or None,
            law_filter=processed.detected_law_refs or None,
        )
        t_hybrid = time.perf_counter()
        logger.info("hybrid_search: %d hits in %.0fms", len(hits), (t_hybrid - t0) * 1000)

        if not rerank or not hits:
            ranked = [
                RankedHit(
                    hit=h,
                    rerank_score=h.score,
                    fused_score=h.score,
                    rerank_rank=i + 1,
                )
                for i, h in enumerate(hits[:top_k])
            ]
            return ranked

        ranked = await do_rerank(query=processed.normalized, hits=hits, top_k=top_k)
        t_rerank = time.perf_counter()
        logger.info(
            "rerank: %d results in %.0fms (total %.0fms)",
            len(ranked),
            (t_rerank - t_hybrid) * 1000,
            (t_rerank - t0) * 1000,
        )
        return ranked
