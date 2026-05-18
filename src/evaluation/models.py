"""Pydantic models for the evaluation framework."""
from pydantic import BaseModel


class TestCase(BaseModel):
    query: str
    expected_articles: list[str]
    expected_law: str | None = None
    notes: str


class RetrievalResult(BaseModel):
    query: str
    returned_articles: list[str]
    hit_at_5: bool
    hit_at_10: bool
    reciprocal_rank: float
    rerank_latency_ms: float


class EvalReport(BaseModel):
    total_cases: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    avg_rerank_latency_ms: float
    failed_cases: list[str]
