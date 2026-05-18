"""Create and configure Qdrant collections with dense + sparse vector support."""
import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_DIM = 1024  # Cohere embed-multilingual-v3.0


def ensure_collection(
    client: QdrantClient,
    name: str,
    vector_size: int = DENSE_DIM,
    recreate: bool = False,
) -> None:
    """Create collection if it doesn't exist; skip if it does (unless recreate=True)."""
    existing = {c.name for c in client.get_collections().collections}

    if name in existing:
        if recreate:
            logger.warning("Dropping existing collection '%s' for reindex", name)
            client.delete_collection(name)
        else:
            logger.info("Collection '%s' already exists — skipping creation", name)
            return

    client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
                hnsw_config=HnswConfigDiff(m=16, ef_construct=128),
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
            )
        },
    )
    logger.info("Created collection '%s' (dim=%d, dense+sparse)", name, vector_size)
