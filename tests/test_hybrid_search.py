"""Tests for hybrid_search module."""

from src.retrieval.hybrid_search import Hit, _sparse_query


class TestSparseQuery:
    def test_returns_sparse_vector(self):
        sv = _sparse_query("αυθαίρετο κτίριο")
        assert len(sv.indices) > 0
        assert len(sv.indices) == len(sv.values)

    def test_all_positive_values(self):
        sv = _sparse_query("πρόστιμο αυθαίρετης κατασκευής")
        assert all(v > 0 for v in sv.values)

    def test_empty_query_gives_empty_vector(self):
        sv = _sparse_query("")
        assert sv.indices == []
        assert sv.values == []

    def test_deterministic(self):
        sv1 = _sparse_query("διαδικασία υπαγωγής")
        sv2 = _sparse_query("διαδικασία υπαγωγής")
        assert sv1.indices == sv2.indices
        assert sv1.values == sv2.values


class TestHitModel:
    def test_hit_all_none_ok(self):
        h = Hit(point_id=1, score=0.5, chunk_id=None, source_file=None,
                law_number=None, fek_ref=None, article=None, paragraph=None,
                page_start=None, page_end=None, scope=None, source_type=None, text=None)
        assert h.point_id == 1
        assert h.article is None

    def test_hit_with_data(self):
        h = Hit(
            point_id=42,
            score=0.9,
            chunk_id="abc123",
            source_file="N_4495_2017.pdf",
            law_number="Ν. 4495/2017",
            fek_ref="ΦΕΚ Α' 167/2017",
            article="Άρθρο 99",
            paragraph="παρ. 1",
            page_start=10,
            page_end=11,
            scope="public",
            source_type="law",
            text="Κείμενο άρθρου...",
        )
        assert h.law_number == "Ν. 4495/2017"
        assert h.article == "Άρθρο 99"
