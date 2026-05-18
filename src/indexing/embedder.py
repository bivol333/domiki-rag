"""Cohere embeddings wrapper with batching and exponential backoff."""
import logging
import time
from typing import Literal

import cohere

from src.config import settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 96
_MAX_RETRIES = 3


def _get_client() -> cohere.ClientV2:
    return cohere.ClientV2(api_key=settings.cohere_api_key)


def embed_chunks(
    texts: list[str],
    input_type: Literal["search_document", "search_query"] = "search_document",
) -> list[list[float]]:
    """Return dense embeddings for a list of texts, batched to 96 per request."""
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[batch_start : batch_start + _BATCH_SIZE]
        embeddings = _embed_batch(client, batch, input_type)
        all_embeddings.extend(embeddings)

    return all_embeddings


def _embed_batch(
    client: cohere.ClientV2,
    texts: list[str],
    input_type: Literal["search_document", "search_query"],
) -> list[list[float]]:
    delay = 1.0
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.embed(
                texts=texts,
                model=settings.embedding_model,
                input_type=input_type,
                embedding_types=["float"],
            )
            return [list(e) for e in response.embeddings.float_]
        except cohere.TooManyRequestsError:
            if attempt == _MAX_RETRIES:
                raise
            logger.warning(
                "Rate limit hit — retrying in %.1fs (attempt %d/%d)", delay, attempt, _MAX_RETRIES
            )
            time.sleep(delay)
            delay *= 2
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                raise RuntimeError(
                    f"Embedding failed after {_MAX_RETRIES} attempts: {exc}"
                ) from exc
            logger.warning(
                "Embedding error: %s — retrying (attempt %d/%d)", exc, attempt, _MAX_RETRIES
            )
            time.sleep(delay)
            delay *= 2

    raise RuntimeError("Unreachable")
