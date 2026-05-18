"""Cohere Rerank 3 wrapper for re-ordering hybrid search hits."""
import asyncio
import logging

import cohere
from pydantic import BaseModel

from src.config import settings
from src.retrieval.hybrid_search import Hit

logger = logging.getLogger(__name__)

_RERANK_MODEL = "rerank-multilingual-v3.0"


class RankedHit(BaseModel):
    hit: Hit
    rerank_score: float
    fused_score: float
    rerank_rank: int


async def rerank(
    query: str,
    hits: list[Hit],
    top_k: int = 10,
) -> list[RankedHit]:
    """Rerank hits with Cohere Rerank 3, returning top_k RankedHit objects."""
    if not hits:
        return []

    documents = [h.text or "" for h in hits]

    client = cohere.AsyncClient(api_key=settings.cohere_api_key)
    response = await _rerank_with_retry(client, query, documents, top_k)

    ranked: list[RankedHit] = []
    for rank_idx, result in enumerate(response.results):
        original_hit = hits[result.index]
        ranked.append(
            RankedHit(
                hit=original_hit,
                rerank_score=result.relevance_score,
                fused_score=original_hit.score,
                rerank_rank=rank_idx + 1,
            )
        )

    logger.info(
        "rerank('%s') → %d results (top rerank_score=%.4f)",
        query[:60],
        len(ranked),
        ranked[0].rerank_score if ranked else 0.0,
    )
    return ranked


async def _rerank_with_retry(
    client: cohere.AsyncClient,
    query: str,
    documents: list[str],
    top_k: int,
    max_retries: int = 3,
) -> cohere.RerankResponse:
    delay = 10.0
    for attempt in range(max_retries):
        try:
            return await client.rerank(
                query=query,
                documents=documents,
                model=_RERANK_MODEL,
                top_n=top_k,
                return_documents=False,
            )
        except cohere.errors.TooManyRequestsError:
            if attempt == max_retries - 1:
                raise
            logger.warning("Cohere rate limit hit, waiting %.0fs before retry %d/%d...",
                           delay, attempt + 1, max_retries - 1)
            await asyncio.sleep(delay)
            delay *= 2
        except Exception:
            if attempt == max_retries - 1:
                raise
            logger.warning("Cohere rerank transient error, retrying once...")
            await asyncio.sleep(2.0)
    raise RuntimeError("unreachable")
