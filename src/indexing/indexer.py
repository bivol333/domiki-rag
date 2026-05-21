"""Upsert Chunk objects into a Qdrant collection with dense + sparse vectors."""
import logging
import math
from collections import Counter

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector

from src.common.tokenizer import token_to_index, tokenize_greek
from src.config import settings
from src.indexing.embedder import embed_chunks
from src.ingestion.models import Chunk

logger = logging.getLogger(__name__)

_UPSERT_BATCH = 64


def _compute_bm25_sparse_vectors(
    chunks: list[Chunk],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[int, float]]:
    """Compute per-chunk BM25 sparse vectors over the batch corpus."""
    tokenized = [tokenize_greek(c.text) for c in chunks]
    n = len(tokenized)
    avg_len = sum(len(t) for t in tokenized) / max(n, 1)

    # Document frequency
    df: Counter[str] = Counter()
    for tokens in tokenized:
        df.update(set(tokens))

    results: list[dict[int, float]] = []
    for tokens in tokenized:
        tf: Counter[str] = Counter(tokens)
        doc_len = len(tokens)
        vec: dict[int, float] = {}
        for term, freq in tf.items():
            idf = math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1)
            score = idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * doc_len / avg_len))
            idx = token_to_index(term)
            vec[idx] = vec.get(idx, 0.0) + score
        results.append(vec)

    return results


def _chunk_payload(chunk: Chunk) -> dict:
    doc = chunk.document
    return {
        "chunk_id": chunk.chunk_id,
        "source_file": doc.source_file,
        "source_type": doc.source_type,
        "scope": doc.scope,
        "title": doc.title,
        "law_number": doc.law_number,
        "fek_ref": doc.fek_ref,
        "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
        "issuing_body": doc.issuing_body,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "article": chunk.article,
        "paragraph": chunk.paragraph,
        "char_count": chunk.char_count,
        "token_count": chunk.token_count,
        "text": chunk.text,
    }


def prepare_points(chunks: list[Chunk], source_hint: str = "") -> list[PointStruct]:
    """Embed chunks and build PointStructs — no Qdrant writes.

    Separating this from the upsert step allows callers to embed ALL files before
    touching the collection (two-phase rebuild pattern: embed everything first,
    only wipe the collection once all embeddings succeed).

    Args:
        chunks: Chunks to embed.
        source_hint: Filename or label forwarded to the embedder for log messages.

    Returns:
        List of PointStruct objects ready for upsert.

    Raises:
        cohere.TooManyRequestsError: Rate limit exhausted after all retries.
        RuntimeError: Any other embedding failure after all retries.
    """
    if not chunks:
        return []

    texts = [c.text for c in chunks]
    logger.info("Embedding %d chunks%s...", len(chunks), f" ({source_hint})" if source_hint else "")
    dense_vecs = embed_chunks(texts, input_type="search_document", source_hint=source_hint)

    logger.info("Computing BM25 sparse vectors%s...", f" ({source_hint})" if source_hint else "")
    sparse_dicts = _compute_bm25_sparse_vectors(chunks)

    points: list[PointStruct] = []
    for chunk, dense, sparse_dict in zip(chunks, dense_vecs, sparse_dicts, strict=True):
        indices = list(sparse_dict.keys())
        values = [sparse_dict[i] for i in indices]
        # Qdrant requires int or UUID; convert 16-char hex to uint64
        point_id = int(chunk.chunk_id, 16)
        points.append(
            PointStruct(
                id=point_id,
                vector={
                    "dense": dense,
                    "sparse": SparseVector(indices=indices, values=values),
                },
                payload=_chunk_payload(chunk),
            )
        )

    return points


def upsert_points(
    points: list[PointStruct],
    collection: str,
    client: QdrantClient,
) -> None:
    """Upsert pre-built PointStructs into Qdrant in batches."""
    for batch_start in range(0, len(points), _UPSERT_BATCH):
        batch = points[batch_start : batch_start + _UPSERT_BATCH]
        client.upsert(collection_name=collection, points=batch)
        logger.info(
            "Upserted %d/%d points into '%s'",
            min(batch_start + _UPSERT_BATCH, len(points)),
            len(points),
            collection,
        )


def index_chunks(
    chunks: list[Chunk],
    collection: str,
    client: QdrantClient | None = None,
    source_hint: str = "",
) -> None:
    """Embed and upsert chunks into Qdrant. Same chunk_id overwrites idempotently.

    Convenience wrapper around prepare_points() + upsert_points().
    For rebuild scenarios, call those functions directly to control the order
    of embedding vs. collection wipe.
    """
    if not chunks:
        logger.info("No chunks to index into '%s'", collection)
        return

    if client is None:
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)

    points = prepare_points(chunks, source_hint=source_hint)
    upsert_points(points, collection, client)
