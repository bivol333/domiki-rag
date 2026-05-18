"""End-to-end QA pipeline: retrieve, then generate a grounded answer."""
import logging
import time
from collections.abc import Iterator

from src.generation.answer_generator import AnswerGenerator
from src.generation.models import AnswerResponse
from src.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


class QAPipeline:
    def __init__(
        self,
        retriever: Retriever,
        generator: AnswerGenerator,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._last_hits = None
        self._last_retrieval_ms = 0.0
        self._last_query = ""

    async def ask(
        self,
        query: str,
        top_k: int = 8,
        initial_k: int = 50,
    ) -> AnswerResponse:
        """Non-streaming. Returns final AnswerResponse."""
        t0 = time.perf_counter()
        hits = await self._retriever.search(
            query=query, top_k=top_k, initial_k=initial_k, rerank=True,
        )
        retrieval_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        response = self._generator.generate(query=query, hits=hits)
        total_ms = (time.perf_counter() - t0) * 1000

        response.timing = {
            "retrieval_ms": retrieval_ms,
            "generation_ms": (time.perf_counter() - t1) * 1000,
            "total_ms": total_ms,
        }
        logger.info(
            "QAPipeline.ask: retrieval=%.0fms generation=%.0fms total=%.0fms",
            retrieval_ms,
            response.timing["generation_ms"],
            total_ms,
        )
        return response

    async def ask_stream(
        self,
        query: str,
        top_k: int = 8,
        initial_k: int = 50,
    ) -> Iterator[str]:
        """Returns the token iterator. Call finalize() after exhaustion."""
        t0 = time.perf_counter()
        hits = await self._retriever.search(
            query=query, top_k=top_k, initial_k=initial_k, rerank=True,
        )
        self._last_retrieval_ms = (time.perf_counter() - t0) * 1000
        self._last_hits = hits
        self._last_query = query

        return self._generator.stream(query=query, hits=hits)

    def finalize_stream(self) -> AnswerResponse:
        """Build AnswerResponse for the last completed stream. Caller must
        ensure the iterator from ask_stream() has been fully consumed."""
        if self._last_hits is None:
            raise RuntimeError("No prior stream — call ask_stream() first.")
        response = self._generator.finalize(self._last_query, self._last_hits)
        generation_ms = response.timing.get("generation_ms", 0.0)
        response.timing = {
            "retrieval_ms": self._last_retrieval_ms,
            "generation_ms": generation_ms,
            "total_ms": self._last_retrieval_ms + generation_ms,
        }
        return response
