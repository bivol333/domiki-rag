"""Tests for QueryLogger: persistence, filtering, feedback, pagination."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.generation.models import AnswerResponse
from src.observability.logger import QueryLogger
from src.retrieval.hybrid_search import Hit
from src.retrieval.reranker import RankedHit


def _make_ranked_hit(article: str = "Άρθρο 99", chunk_id: str = "abc123") -> RankedHit:
    h = Hit(
        point_id=1, score=0.5, chunk_id=chunk_id,
        source_file="law.pdf", law_number="Ν. 4495/2017",
        fek_ref=None, article=article, paragraph=None,
        page_start=10, page_end=12, scope="public",
        source_type="law", text="δείγμα κειμένου",
    )
    return RankedHit(hit=h, rerank_score=0.91, fused_score=0.7, rerank_rank=1)


def _make_response(
    refused: bool = False,
    n_chunks: int = 2,
    answer_text: str = "απάντηση [Source: chunk_1].",
) -> AnswerResponse:
    chunks = [_make_ranked_hit(f"Άρθρο {99 + i}", f"chunk_{i}") for i in range(n_chunks)]
    return AnswerResponse(
        query="δείγμα ερώτησης",
        answer_text=answer_text,
        citations=[],
        source_chunks=chunks,
        refused=refused,
        has_invalid_citations=False,
        timing={"total_ms": 1500.0},
        token_usage={"input_tokens": 100, "output_tokens": 50},
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_logs.db"


@pytest.fixture
def query_logger(db_path: Path) -> QueryLogger:
    return QueryLogger(db_path=db_path)


class TestRoundtrip:
    def test_insert_and_retrieve(self, query_logger: QueryLogger):
        resp = _make_response()
        qid = query_logger.log("sess-1", "ερώτηση 1", resp)
        assert qid > 0

        entry = query_logger.get_by_id(qid)
        assert entry is not None
        assert entry.session_id == "sess-1"
        assert entry.query == "ερώτηση 1"
        assert entry.answer == resp.answer_text
        assert entry.refused is False
        assert entry.feedback is None
        assert entry.feedback_comment is None

    def test_chunks_used_roundtrips_as_json(self, query_logger: QueryLogger):
        resp = _make_response(n_chunks=3)
        qid = query_logger.log("sess-x", "q", resp)
        entry = query_logger.get_by_id(qid)
        assert len(entry.chunks_used) == 3
        assert entry.chunks_used[0]["article"] == "Άρθρο 99"
        assert entry.chunks_used[0]["law_number"] == "Ν. 4495/2017"
        assert entry.chunks_used[0]["chunk_id"] == "chunk_0"
        assert entry.chunks_used[0]["page_start"] == 10

    def test_refused_flag_persisted(self, query_logger: QueryLogger):
        resp = _make_response(refused=True, answer_text="Δεν βρίσκω επαρκή πληροφορία...")
        qid = query_logger.log("s", "q", resp)
        assert query_logger.get_by_id(qid).refused is True


class TestSessionHistory:
    def test_history_returns_most_recent_first(self, query_logger: QueryLogger):
        ids = [query_logger.log("sess-A", f"q{i}", _make_response()) for i in range(3)]
        history = query_logger.get_session_history("sess-A")
        assert len(history) == 3
        assert [e.id for e in history] == list(reversed(ids))

    def test_history_limited(self, query_logger: QueryLogger):
        for i in range(25):
            query_logger.log("sess-A", f"q{i}", _make_response())
        history = query_logger.get_session_history("sess-A", limit=20)
        assert len(history) == 20

    def test_sessions_isolated(self, query_logger: QueryLogger):
        query_logger.log("sess-A", "a1", _make_response())
        query_logger.log("sess-A", "a2", _make_response())
        query_logger.log("sess-B", "b1", _make_response())
        a_hist = query_logger.get_session_history("sess-A")
        b_hist = query_logger.get_session_history("sess-B")
        assert len(a_hist) == 2
        assert len(b_hist) == 1
        assert b_hist[0].query == "b1"


class TestFeedback:
    def test_add_positive_feedback(self, query_logger: QueryLogger):
        qid = query_logger.log("s", "q", _make_response())
        query_logger.add_feedback(qid, "positive", comment="πολύ καλή απάντηση")
        entry = query_logger.get_by_id(qid)
        assert entry.feedback == "positive"
        assert entry.feedback_comment == "πολύ καλή απάντηση"

    def test_add_negative_feedback_no_comment(self, query_logger: QueryLogger):
        qid = query_logger.log("s", "q", _make_response())
        query_logger.add_feedback(qid, "negative")
        entry = query_logger.get_by_id(qid)
        assert entry.feedback == "negative"
        assert entry.feedback_comment is None

    def test_feedback_overwrites(self, query_logger: QueryLogger):
        qid = query_logger.log("s", "q", _make_response())
        query_logger.add_feedback(qid, "positive", "ok")
        query_logger.add_feedback(qid, "negative", "actually no")
        entry = query_logger.get_by_id(qid)
        assert entry.feedback == "negative"
        assert entry.feedback_comment == "actually no"

    def test_feedback_unknown_id_raises(self, query_logger: QueryLogger):
        with pytest.raises(ValueError, match="No query with id"):
            query_logger.add_feedback(9999, "positive")

    def test_feedback_invalid_value_raises(self, query_logger: QueryLogger):
        qid = query_logger.log("s", "q", _make_response())
        with pytest.raises(ValueError):
            query_logger.add_feedback(qid, "maybe")  # type: ignore[arg-type]


class TestAdminFilters:
    def test_refused_only_filter(self, query_logger: QueryLogger):
        query_logger.log("s", "ok", _make_response(refused=False))
        query_logger.log("s", "no", _make_response(refused=True))
        all_q = query_logger.get_all_queries()
        refused = query_logger.get_all_queries(refused_only=True)
        assert len(all_q) == 2
        assert len(refused) == 1
        assert refused[0].refused is True

    def test_feedback_positive_negative_none(self, query_logger: QueryLogger):
        q1 = query_logger.log("s", "a", _make_response())
        q2 = query_logger.log("s", "b", _make_response())
        query_logger.log("s", "c", _make_response())
        query_logger.add_feedback(q1, "positive")
        query_logger.add_feedback(q2, "negative")

        pos = query_logger.get_all_queries(feedback_filter="positive")
        neg = query_logger.get_all_queries(feedback_filter="negative")
        no_fb = query_logger.get_all_queries(feedback_filter="none")
        assert len(pos) == 1
        assert len(neg) == 1
        assert len(no_fb) == 1
        assert pos[0].id == q1
        assert no_fb[0].query == "c"

    def test_date_range_filter(self, query_logger: QueryLogger):
        # Log 3 queries (all "now"); use a date_from in the future to filter them all out
        for q in ("q1", "q2", "q3"):
            query_logger.log("s", q, _make_response())
        future = datetime.now() + timedelta(days=1)
        past = datetime.now() - timedelta(days=1)
        assert query_logger.count_total(date_from=future) == 0
        assert query_logger.count_total(date_from=past) == 3
        assert query_logger.count_total(date_to=past) == 0


class TestPagination:
    def test_limit_and_offset(self, query_logger: QueryLogger):
        ids = [query_logger.log("s", f"q{i}", _make_response()) for i in range(10)]
        page1 = query_logger.get_all_queries(limit=4, offset=0)
        page2 = query_logger.get_all_queries(limit=4, offset=4)
        page3 = query_logger.get_all_queries(limit=4, offset=8)
        assert [e.id for e in page1] == ids[-1:-5:-1]  # last 4, descending
        assert [e.id for e in page2] == ids[-5:-9:-1]
        assert len(page3) == 2

    def test_count_matches_filters(self, query_logger: QueryLogger):
        for _ in range(5):
            query_logger.log("s", "x", _make_response(refused=False))
        for _ in range(3):
            query_logger.log("s", "y", _make_response(refused=True))
        assert query_logger.count_total() == 8
        assert query_logger.count_total(refused_only=True) == 3


class TestInitialization:
    def test_creates_db_on_first_use(self, tmp_path: Path):
        db = tmp_path / "fresh.db"
        assert not db.exists()
        QueryLogger(db_path=db)
        assert db.exists()
