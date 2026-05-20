"""Pydantic models for answer generation."""
from pydantic import BaseModel

from src.retrieval.reranker import RankedHit


class Citation(BaseModel):
    chunk_id: str
    law_number: str | None
    article: str | None
    paragraph: str | None
    page_start: int | None
    page_end: int | None
    source_file: str
    label: str  # e.g. "Ν. 4495/2017, Άρθρο 100, σελ. 23"


class AnswerResponse(BaseModel):
    query: str
    answer_text: str
    citations: list[Citation]
    source_chunks: list[RankedHit]
    refused: bool
    has_invalid_citations: bool = False
    timing: dict[str, float]
    token_usage: dict[str, int]
    query_id: int | None = None  # set when the response has been persisted by QueryLogger
