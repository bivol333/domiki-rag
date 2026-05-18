"""Anthropic Claude client wrapper supporting streaming and non-streaming generation."""
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

import anthropic

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    text: str
    input_tokens: int
    output_tokens: int
    elapsed_ms: float


@dataclass
class StreamingGenerationResult:
    """Yielded after a stream completes; carries final text and usage."""
    text: str
    input_tokens: int
    output_tokens: int
    elapsed_ms: float


class ClaudeClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        self._model = model or settings.claude_model

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
    ) -> GenerationResult:
        """Non-streaming generation. Returns final text + token usage."""
        t0 = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            logger.warning("Anthropic transient error: %s — retrying once", e)
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return GenerationResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            elapsed_ms=elapsed_ms,
        )

    def stream(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Stream text deltas. After the iterator completes, call
        get_last_stream_result() to retrieve final text + token usage."""
        t0 = time.perf_counter()
        chunks: list[str] = []
        input_tokens = 0
        output_tokens = 0

        with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for delta in stream.text_stream:
                chunks.append(delta)
                yield delta

            final_message = stream.get_final_message()
            input_tokens = final_message.usage.input_tokens
            output_tokens = final_message.usage.output_tokens

        elapsed_ms = (time.perf_counter() - t0) * 1000
        self._last_stream_result = StreamingGenerationResult(
            text="".join(chunks),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed_ms,
        )

    def get_last_stream_result(self) -> StreamingGenerationResult:
        if not hasattr(self, "_last_stream_result"):
            raise RuntimeError("No completed stream yet; call stream() and exhaust it first.")
        return self._last_stream_result
