"""Run all test cases through the retriever and compute eval metrics."""
import asyncio
import logging
import time

from src.evaluation.models import EvalReport, RetrievalResult, TestCase
from src.evaluation.test_cases import TEST_CASES
from src.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


def _articles_in_results(returned: list[str], expected: list[str]) -> bool:
    returned_lower = {a.lower() for a in returned}
    return any(e.lower() in returned_lower for e in expected)


def _reciprocal_rank(returned: list[str], expected: list[str]) -> float:
    returned_lower = [a.lower() for a in returned]
    expected_lower = {e.lower() for e in expected}
    for i, art in enumerate(returned_lower):
        if art in expected_lower:
            return 1.0 / (i + 1)
    return 0.0


async def _eval_case(
    retriever: Retriever,
    case: TestCase,
) -> RetrievalResult:
    t0 = time.perf_counter()
    results = await retriever.search(query=case.query, top_k=10, initial_k=50, rerank=True)
    latency_ms = (time.perf_counter() - t0) * 1000

    returned_articles = [r.hit.article for r in results if r.hit.article]

    hit5 = _articles_in_results(returned_articles[:5], case.expected_articles)
    hit10 = _articles_in_results(returned_articles[:10], case.expected_articles)
    rr = _reciprocal_rank(returned_articles[:10], case.expected_articles)

    return RetrievalResult(
        query=case.query,
        returned_articles=returned_articles,
        hit_at_5=hit5,
        hit_at_10=hit10,
        reciprocal_rank=rr,
        rerank_latency_ms=latency_ms,
    )


async def run_eval(
    cases: list[TestCase] | None = None,
    collection: str | None = None,
) -> EvalReport:
    from src.config import settings

    cases = cases or TEST_CASES
    retriever = Retriever(
        collection=collection or settings.public_collection,
    )

    results: list[RetrievalResult] = []
    for i, case in enumerate(cases):
        logger.info("Evaluating (%d/%d): %s", i + 1, len(cases), case.query)
        result = await _eval_case(retriever, case)
        results.append(result)
        if i < len(cases) - 1:
            await asyncio.sleep(7)  # stay under 10 rerank calls/minute on trial key

    n = len(results)
    recall5 = sum(1 for r in results if r.hit_at_5) / n
    recall10 = sum(1 for r in results if r.hit_at_10) / n
    mrr = sum(r.reciprocal_rank for r in results) / n
    avg_latency = sum(r.rerank_latency_ms for r in results) / n
    failed = [r.query for r in results if not r.hit_at_10]

    return EvalReport(
        total_cases=n,
        recall_at_5=recall5,
        recall_at_10=recall10,
        mrr=mrr,
        avg_rerank_latency_ms=avg_latency,
        failed_cases=failed,
    )


def format_report(report: EvalReport, results: list[RetrievalResult] | None = None) -> str:
    lines = [
        "## Αποτελέσματα Αξιολόγησης Ανάκτησης",
        "",
        "| Μετρική | Τιμή |",
        "|---------|------|",
        f"| Recall@5 | {report.recall_at_5:.1%} |",
        f"| Recall@10 | {report.recall_at_10:.1%} |",
        f"| MRR | {report.mrr:.3f} |",
        f"| Avg Latency (ms) | {report.avg_rerank_latency_ms:.0f} |",
        f"| Total Cases | {report.total_cases} |",
        "",
    ]

    if report.failed_cases:
        lines.append("### Αποτυχημένες Περιπτώσεις (Recall@10 = 0)")
        for q in report.failed_cases:
            lines.append(f"- {q}")
        lines.append("")

    status = "PASS" if report.recall_at_5 >= 0.6 else "FAIL"
    threshold_sym = "≥" if report.recall_at_5 >= 0.6 else "<"
    lines.append(f"**Κατάσταση: {status}** (Recall@5 {threshold_sym} 0.60)")

    return "\n".join(lines)
