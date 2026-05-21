"""Cohere embeddings wrapper with batching and exponential backoff."""
import logging
import time
from typing import Literal

import cohere

from src.config import settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 96
_MAX_RETRIES = 5
# Pause between consecutive batches to stay under per-minute rate limits.
# Cohere free/trial tier allows ~100 API calls/minute; 0.5 s gives ~120 calls/minute
# headroom while keeping ingestion reasonably fast.
_INTER_BATCH_DELAY = 0.5  # seconds


def _get_client() -> cohere.ClientV2:
    return cohere.ClientV2(api_key=settings.cohere_api_key)


def embed_chunks(
    texts: list[str],
    input_type: Literal["search_document", "search_query"] = "search_document",
    source_hint: str = "",
) -> list[list[float]]:
    """Return dense embeddings for a list of texts, batched to 96 per request.

    Args:
        texts: Texts to embed.
        input_type: Cohere input type tag.
        source_hint: Filename or label used in log messages for easier diagnosis.
    """
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []

    batches = range(0, len(texts), _BATCH_SIZE)
    for batch_idx, batch_start in enumerate(batches):
        if batch_idx > 0:
            time.sleep(_INTER_BATCH_DELAY)
        batch = texts[batch_start : batch_start + _BATCH_SIZE]
        batch_label = (
            f"{source_hint} batch {batch_idx + 1}/{len(batches)}"
            if source_hint
            else f"batch {batch_idx + 1}/{len(batches)}"
        )
        embeddings = _embed_batch(client, batch, input_type, label=batch_label)
        all_embeddings.extend(embeddings)

    return all_embeddings


def _embed_batch(
    client: cohere.ClientV2,
    texts: list[str],
    input_type: Literal["search_document", "search_query"],
    label: str = "batch",
) -> list[list[float]]:
    """Embed one batch with exponential-backoff retry.

    Retries up to _MAX_RETRIES times total.  Backoff sequence: 1 s, 2 s, 4 s, 8 s, 16 s.
    Raises the original exception on final failure.
    """
    delay = 1.0
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.embed(
                texts=texts,
                model=settings.embedding_model,
                input_type=input_type,
                embedding_types=["float"],
            )
            if attempt > 1:
                logger.info(
                    "Embedding succeeded on attempt %d/%d (%s)", attempt, _MAX_RETRIES, label
                )
            return [list(e) for e in response.embeddings.float_]
        except cohere.TooManyRequestsError:
            if attempt == _MAX_RETRIES:
                logger.error(
                    "Rate limit exhausted after %d attempts (%s) — giving up", _MAX_RETRIES, label
                )
                raise
            logger.warning(
                "Rate limit hit (%s) — retry %d/%d in %.0fs",
                label,
                attempt,
                _MAX_RETRIES - 1,
                delay,
            )
            time.sleep(delay)
            delay *= 2
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                logger.error(
                    "Embedding failed after %d attempts (%s): %s", _MAX_RETRIES, label, exc
                )
                raise RuntimeError(
                    f"Embedding failed after {_MAX_RETRIES} attempts ({label}): {exc}"
                ) from exc
            logger.warning(
                "Embedding error (%s): %s — retry %d/%d in %.0fs",
                label,
                exc,
                attempt,
                _MAX_RETRIES - 1,
                delay,
            )
            time.sleep(delay)
            delay *= 2

    raise RuntimeError("Unreachable")
