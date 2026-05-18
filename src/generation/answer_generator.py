"""Compose query + retrieved hits into a grounded Greek answer via Claude."""
import logging
import re
from collections.abc import Iterator

from src.generation.claude_client import ClaudeClient
from src.generation.models import AnswerResponse, Citation
from src.generation.prompts import (
    INVALID_CITATION_PLACEHOLDER,
    REFUSAL_PHRASE,
    SYSTEM_PROMPT,
    build_user_message,
)
from src.retrieval.reranker import RankedHit

logger = logging.getLogger(__name__)

# [Source: chunk_3] or [Source: chunk_1, chunk_4, chunk_2]
_CITATION_RE = re.compile(r"\[Source:\s*((?:chunk_\d+\s*,?\s*)+)\]", re.IGNORECASE)
_CHUNK_NUM_RE = re.compile(r"chunk_(\d+)", re.IGNORECASE)


def _label_for_hit(hit: RankedHit) -> str:
    h = hit.hit
    parts: list[str] = []
    if h.law_number:
        parts.append(h.law_number)
    if h.article:
        parts.append(h.article)
    if h.paragraph:
        parts.append(h.paragraph)
    if h.page_start is not None:
        if h.page_end is not None and h.page_end != h.page_start:
            parts.append(f"σελ. {h.page_start}-{h.page_end}")
        else:
            parts.append(f"σελ. {h.page_start}")
    return ", ".join(parts) if parts else (h.source_file or "—")


def _hit_to_citation(hit: RankedHit) -> Citation:
    h = hit.hit
    return Citation(
        chunk_id=h.chunk_id or "",
        law_number=h.law_number,
        article=h.article,
        paragraph=h.paragraph,
        page_start=h.page_start,
        page_end=h.page_end,
        source_file=h.source_file or "",
        label=_label_for_hit(hit),
    )


def parse_citations(
    answer_text: str,
    hits: list[RankedHit],
) -> tuple[str, list[Citation], bool]:
    """Extract chunk references from answer text.

    Returns (cleaned_text, citations, has_invalid).
    - cleaned_text: original text with markers referring to nonexistent chunks
      replaced by INVALID_CITATION_PLACEHOLDER. Valid markers kept verbatim.
    - citations: ordered, deduplicated list of Citations for chunks actually cited.
    - has_invalid: True if at least one cited chunk index was out of range.
    """
    n_hits = len(hits)
    seen_indices: list[int] = []
    has_invalid = False

    def _replace(match: re.Match) -> str:
        nonlocal has_invalid
        inner = match.group(1)
        nums = [int(m.group(1)) for m in _CHUNK_NUM_RE.finditer(inner)]
        valid_nums: list[int] = []
        for n in nums:
            if 1 <= n <= n_hits:
                valid_nums.append(n)
                idx = n - 1
                if idx not in seen_indices:
                    seen_indices.append(idx)
            else:
                logger.warning(
                    "Claude cited chunk_%d but only %d chunks were sent — dropping",
                    n, n_hits,
                )
                has_invalid = True
        if not valid_nums:
            return INVALID_CITATION_PLACEHOLDER
        if len(valid_nums) == len(nums):
            return match.group(0)
        # mixed: keep valid ones, drop invalid
        joined = ", ".join(f"chunk_{n}" for n in valid_nums)
        return f"[Source: {joined}]"

    cleaned = _CITATION_RE.sub(_replace, answer_text)
    citations = [_hit_to_citation(hits[i]) for i in seen_indices]
    return cleaned, citations, has_invalid


def _is_refusal(text: str) -> bool:
    return REFUSAL_PHRASE in text


class AnswerGenerator:
    def __init__(self, claude_client: ClaudeClient) -> None:
        self._client = claude_client

    def generate(
        self,
        query: str,
        hits: list[RankedHit],
        max_tokens: int = 2048,
    ) -> AnswerResponse:
        """Non-streaming end-to-end generation."""
        user_msg = build_user_message(query, hits)
        result = self._client.generate(
            system=SYSTEM_PROMPT,
            user=user_msg,
            max_tokens=max_tokens,
        )
        cleaned, citations, has_invalid = parse_citations(result.text, hits)
        return AnswerResponse(
            query=query,
            answer_text=cleaned,
            citations=citations,
            source_chunks=hits,
            refused=_is_refusal(cleaned),
            has_invalid_citations=has_invalid,
            timing={"generation_ms": result.elapsed_ms},
            token_usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )

    def stream(
        self,
        query: str,
        hits: list[RankedHit],
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Yield raw text deltas from Claude. Call finalize(query, hits) after exhaustion."""
        user_msg = build_user_message(query, hits)
        yield from self._client.stream(
            system=SYSTEM_PROMPT,
            user=user_msg,
            max_tokens=max_tokens,
        )

    def finalize(
        self,
        query: str,
        hits: list[RankedHit],
    ) -> AnswerResponse:
        """Build an AnswerResponse from the most recently completed stream."""
        result = self._client.get_last_stream_result()
        cleaned, citations, has_invalid = parse_citations(result.text, hits)
        return AnswerResponse(
            query=query,
            answer_text=cleaned,
            citations=citations,
            source_chunks=hits,
            refused=_is_refusal(cleaned),
            has_invalid_citations=has_invalid,
            timing={"generation_ms": result.elapsed_ms},
            token_usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
