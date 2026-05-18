"""Tests for reranker module (mocked Cohere for unit tests)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieval.hybrid_search import Hit
from src.retrieval.reranker import RankedHit, rerank


def _make_hit(article: str | None = None, score: float = 0.5, text: str = "κείμενο") -> Hit:
    return Hit(
        point_id=1,
        score=score,
        chunk_id=None,
        source_file=None,
        law_number=None,
        fek_ref=None,
        article=article,
        paragraph=None,
        page_start=None,
        page_end=None,
        scope=None,
        source_type=None,
        text=text,
    )


class TestRankedHit:
    def test_ranked_hit_construction(self):
        h = _make_hit("Άρθρο 99")
        rh = RankedHit(hit=h, rerank_score=0.95, fused_score=0.7, rerank_rank=1)
        assert rh.rerank_score == 0.95
        assert rh.hit.article == "Άρθρο 99"
        assert rh.rerank_rank == 1


class TestRerank:
    @pytest.mark.asyncio
    async def test_empty_hits_returns_empty(self):
        result = await rerank("ερώτηση", [], top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_returns_ranked_hits(self):
        hits = [
            _make_hit("Άρθρο 99", score=0.8, text="Δικαιολογητικά υπαγωγής αυθαιρέτων"),
            _make_hit("Άρθρο 100", score=0.6, text="Πρόστιμο αυθαίρετης κατασκευής"),
            _make_hit("Άρθρο 101", score=0.5, text="Ειδική εισφορά"),
        ]

        mock_result_0 = MagicMock()
        mock_result_0.index = 1
        mock_result_0.relevance_score = 0.95

        mock_result_1 = MagicMock()
        mock_result_1.index = 0
        mock_result_1.relevance_score = 0.88

        mock_response = MagicMock()
        mock_response.results = [mock_result_0, mock_result_1]

        mock_client = AsyncMock()
        mock_client.rerank = AsyncMock(return_value=mock_response)
        mock_client.close = AsyncMock()

        with patch("src.retrieval.reranker.cohere.AsyncClient", return_value=mock_client):
            ranked = await rerank("πρόστιμο αυθαίρετης", hits, top_k=2)

        assert len(ranked) == 2
        assert ranked[0].hit.article == "Άρθρο 100"
        assert ranked[0].rerank_score == pytest.approx(0.95)
        assert ranked[0].rerank_rank == 1
        assert ranked[1].hit.article == "Άρθρο 99"
        assert ranked[1].rerank_rank == 2

    @pytest.mark.asyncio
    async def test_fused_score_preserved(self):
        hits = [_make_hit("Άρθρο 99", score=0.77, text="test")]

        mock_result = MagicMock()
        mock_result.index = 0
        mock_result.relevance_score = 0.9

        mock_response = MagicMock()
        mock_response.results = [mock_result]

        mock_client = AsyncMock()
        mock_client.rerank = AsyncMock(return_value=mock_response)
        mock_client.close = AsyncMock()

        with patch("src.retrieval.reranker.cohere.AsyncClient", return_value=mock_client):
            ranked = await rerank("test", hits, top_k=1)

        assert ranked[0].fused_score == pytest.approx(0.77)
        assert ranked[0].rerank_score == pytest.approx(0.9)
