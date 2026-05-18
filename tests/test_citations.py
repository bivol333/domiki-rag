"""Tests for citation parsing in answer text."""
from src.generation.answer_generator import parse_citations
from src.generation.prompts import INVALID_CITATION_PLACEHOLDER
from src.retrieval.hybrid_search import Hit
from src.retrieval.reranker import RankedHit


def _make_hit(
    article: str,
    chunk_id: str,
    law: str = "Ν. 4495/2017",
    page_start: int = 1,
    page_end: int = 2,
    source_file: str = "law.pdf",
    text: str = "δείγμα",
) -> RankedHit:
    h = Hit(
        point_id=1,
        score=0.5,
        chunk_id=chunk_id,
        source_file=source_file,
        law_number=law,
        fek_ref=None,
        article=article,
        paragraph=None,
        page_start=page_start,
        page_end=page_end,
        scope="public",
        source_type="law",
        text=text,
    )
    return RankedHit(hit=h, rerank_score=0.9, fused_score=0.7, rerank_rank=1)


class TestParseCitations:
    def test_single_valid_citation(self):
        hits = [_make_hit("Άρθρο 99", "abc123")]
        text = "Η διαδικασία υπαγωγής περιγράφεται στο [Source: chunk_1]."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert cleaned == text
        assert len(cites) == 1
        assert cites[0].article == "Άρθρο 99"
        assert cites[0].chunk_id == "abc123"
        assert not invalid

    def test_multiple_chunks_in_one_marker(self):
        hits = [_make_hit("Άρθρο 99", "a"), _make_hit("Άρθρο 100", "b")]
        text = "Συνδυασμός [Source: chunk_1, chunk_2]."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert cleaned == text
        assert len(cites) == 2
        assert {c.article for c in cites} == {"Άρθρο 99", "Άρθρο 100"}
        assert not invalid

    def test_deduplication_across_markers(self):
        hits = [_make_hit("Άρθρο 99", "a"), _make_hit("Άρθρο 100", "b")]
        text = "[Source: chunk_1] και πάλι [Source: chunk_1] και [Source: chunk_2]."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert cleaned == text
        assert len(cites) == 2
        # Order matches first appearance
        assert cites[0].article == "Άρθρο 99"
        assert cites[1].article == "Άρθρο 100"

    def test_invalid_chunk_number_replaced(self):
        hits = [_make_hit("Άρθρο 99", "a")]
        text = "Πληροφορία [Source: chunk_5]."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert "[Source: chunk_5]" not in cleaned
        assert INVALID_CITATION_PLACEHOLDER in cleaned
        assert cites == []
        assert invalid

    def test_mixed_valid_invalid_keeps_valid(self):
        hits = [_make_hit("Άρθρο 99", "a")]
        text = "Πληροφορία [Source: chunk_1, chunk_9]."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert "[Source: chunk_1]" in cleaned
        assert "chunk_9" not in cleaned
        assert len(cites) == 1
        assert invalid

    def test_no_citations_returns_empty_list(self):
        hits = [_make_hit("Άρθρο 99", "a")]
        text = "Καθαρό κείμενο χωρίς αναφορές."
        cleaned, cites, invalid = parse_citations(text, hits)
        assert cleaned == text
        assert cites == []
        assert not invalid

    def test_label_includes_law_article_pages(self):
        hits = [_make_hit("Άρθρο 100", "x", page_start=23, page_end=25)]
        text = "[Source: chunk_1]"
        _, cites, _ = parse_citations(text, hits)
        assert cites[0].label == "Ν. 4495/2017, Άρθρο 100, σελ. 23-25"

    def test_label_single_page(self):
        hits = [_make_hit("Άρθρο 100", "x", page_start=23, page_end=23)]
        _, cites, _ = parse_citations("[Source: chunk_1]", hits)
        assert "σελ. 23" in cites[0].label
        assert "σελ. 23-23" not in cites[0].label

    def test_case_insensitive_match(self):
        hits = [_make_hit("Άρθρο 99", "a")]
        text = "[source: CHUNK_1]"
        cleaned, cites, invalid = parse_citations(text, hits)
        assert len(cites) == 1
        assert not invalid

    def test_realistic_greek_answer(self):
        hits = [
            _make_hit("Άρθρο 99", "id1", page_start=18, page_end=22),
            _make_hit("Άρθρο 100", "id2", page_start=23, page_end=27),
        ]
        text = (
            "Η διαδικασία υπαγωγής αυθαιρέτου περιλαμβάνει την υποβολή "
            "δικαιολογητικών [Source: chunk_1] και την καταβολή ειδικού "
            "προστίμου [Source: chunk_2]. Τα δικαιολογητικά και το πρόστιμο "
            "ορίζονται στις σχετικές διατάξεις [Source: chunk_1, chunk_2]."
        )
        cleaned, cites, invalid = parse_citations(text, hits)
        assert cleaned == text
        assert len(cites) == 2
        assert not invalid
