"""Hybrid dense + sparse search using Qdrant's native RRF fusion."""
import logging

from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Fusion, FusionQuery, Prefetch, SparseVector

from src.common.tokenizer import text_to_sparse
from src.config import settings
from src.indexing.embedder import embed_chunks

logger = logging.getLogger(__name__)

_COHERE_QUERY_TYPE = "search_query"


class Hit(BaseModel):
    point_id: int
    score: float
    chunk_id: str | None
    source_file: str | None
    law_number: str | None
    fek_ref: str | None
    article: str | None
    paragraph: str | None
    page_start: int | None
    page_end: int | None
    scope: str | None
    source_type: str | None
    text: str | None


def _embed_query(query: str) -> list[float]:
    vecs = embed_chunks([query], input_type=_COHERE_QUERY_TYPE)
    return vecs[0]


def _sparse_query(query: str) -> SparseVector:
    vec = text_to_sparse(query)
    indices = list(vec.keys())
    values = [vec[i] for i in indices]
    return SparseVector(indices=indices, values=values)


def _payload_to_hit(point_id: int, score: float, payload: dict | None) -> Hit:
    p = payload or {}
    return Hit(
        point_id=point_id,
        score=score,
        chunk_id=p.get("chunk_id"),
        source_file=p.get("source_file"),
        law_number=p.get("law_number"),
        fek_ref=p.get("fek_ref"),
        article=p.get("article"),
        paragraph=p.get("paragraph"),
        page_start=p.get("page_start"),
        page_end=p.get("page_end"),
        scope=p.get("scope"),
        source_type=p.get("source_type"),
        text=p.get("text"),
    )


async def hybrid_search(
    query: str,
    collection: str = settings.public_collection,
    initial_k: int = 50,
    article_filter: list[str] | None = None,
    law_filter: list[str] | None = None,
    client: AsyncQdrantClient | None = None,
) -> list[Hit]:
    """Return up to initial_k hits using Qdrant native RRF over dense + sparse."""
    own_client = client is None
    if own_client:
        client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )

    try:
        dense_vec = _embed_query(query)
        sparse_vec = _sparse_query(query)

        prefetches = [
            Prefetch(query=dense_vec, using="dense", limit=initial_k),
            Prefetch(query=sparse_vec, using="sparse", limit=initial_k),
        ]

        response = await client.query_points(
            collection_name=collection,
            prefetch=prefetches,
            query=FusionQuery(fusion=Fusion.RRF),
            limit=initial_k,
            with_payload=True,
        )
    finally:
        if own_client:
            await client.close()

    hits = [
        _payload_to_hit(int(pt.id), pt.score, pt.payload)
        for pt in response.points
    ]
    logger.info(
        "hybrid_search('%s', collection=%s) → %d hits",
        query[:60],
        collection,
        len(hits),
    )
    return hits
