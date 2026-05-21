"""Tests for chunker."""

from src.ingestion.chunker import MAX_TOKENS, chunk_pages
from src.ingestion.models import DocumentMetadata
from src.ingestion.pdf_parser import PageContent


def _doc(source_file: str = "test.pdf") -> DocumentMetadata:
    return DocumentMetadata(
        source_file=source_file,
        source_type="law",
        scope="public",
        law_number="Ν. 4495/2017",
        fek_ref="ΦΕΚ Α' 232/2017",
        total_pages=1,
    )


def _page(text: str, num: int = 1) -> PageContent:
    return PageContent(page_number=num, text=text, has_tables=False)


def _word_repeat(n: int) -> str:
    return " ".join(["κτίριο"] * n)


class TestChunkFitsInArticle:
    def test_single_article_single_chunk(self):
        text = "Άρθρο 1\n\n" + _word_repeat(50)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        assert len(chunks) == 1
        assert chunks[0].article == "Άρθρο 1"

    def test_article_label_in_metadata(self):
        text = "Άρθρο 5\n\nΟρισμοί και ερμηνείες."
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        assert chunks[0].article == "Άρθρο 5"

    def test_header_context_in_every_chunk(self):
        text = "Άρθρο 1\n\n" + _word_repeat(50)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        for chunk in chunks:
            assert chunk.text.startswith("[ΠΗΓΗ:")

    def test_header_contains_law_number(self):
        text = "Άρθρο 1\n\n" + _word_repeat(50)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        assert "4495" in chunks[0].text


class TestLargeArticleSplitsByParagraph:
    def test_oversized_article_splits_into_multiple_chunks(self):
        paragraphs = "\n\n".join(f"παρ. {i}\n" + _word_repeat(120) for i in range(1, 5))
        text = f"Άρθρο 10\n\n{paragraphs}"
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        assert len(chunks) > 1

    def test_all_paragraph_chunks_carry_article_label(self):
        paragraphs = "\n\n".join(f"παρ. {i}\n" + _word_repeat(120) for i in range(1, 5))
        text = f"Άρθρο 10\n\n{paragraphs}"
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        for chunk in chunks:
            assert chunk.article == "Άρθρο 10"


class TestTokenLimits:
    def test_no_chunk_exceeds_max_tokens_significantly(self):
        paragraphs = "\n\n".join(f"παρ. {i}\n" + _word_repeat(50) for i in range(1, 20))
        text = f"Άρθρο 1\n\n{paragraphs}"
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        for chunk in chunks:
            # Allow some slack for header
            assert chunk.token_count <= MAX_TOKENS + 50

    def test_token_count_field_is_accurate(self):
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        text = "Άρθρο 1\n\nΜικρό κείμενο."
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        for chunk in chunks:
            actual = len(enc.encode(chunk.text))
            assert chunk.token_count == actual


class TestDeterminism:
    def test_chunk_id_is_deterministic(self):
        text = "Άρθρο 1\n\nΚείμενο για δοκιμή."
        pages = [_page(text)]
        chunks1 = chunk_pages(pages, _doc())
        chunks2 = chunk_pages(pages, _doc())
        ids1 = [c.chunk_id for c in chunks1]
        ids2 = [c.chunk_id for c in chunks2]
        assert ids1 == ids2

    def test_idempotent_produces_identical_chunks(self):
        text = "Άρθρο 1\n\nΚείμενο.\n\nΆρθρο 2\n\nΆλλο κείμενο."
        pages = [_page(text)]
        run1 = chunk_pages(pages, _doc())
        run2 = chunk_pages(pages, _doc())
        assert [c.model_dump() for c in run1] == [c.model_dump() for c in run2]


class TestMultipleArticles:
    def test_two_articles_two_chunks(self):
        text = (
            "Άρθρο 1\n\n" + _word_repeat(50) +
            "\n\nΆρθρο 2\n\n" + _word_repeat(50)
        )
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        articles = {c.article for c in chunks}
        assert "Άρθρο 1" in articles
        assert "Άρθρο 2" in articles


# ── Sliding-window fallback heuristic ────────────────────────────────────────
#
# Documents that don't fit the "well-formed law with many articles" pattern
# (e.g. PD-24-1985-Ektos-Sxediou: 12 pages of preamble + 1 detected Άρθρο 1)
# must NOT silently lose their preamble.  These tests guard the fallback.

class TestSlidingWindowFallback:
    """Heuristic: documents with large preambles or weak article structure
    chunk the WHOLE document via sliding window instead of dropping the preamble."""

    def _make_preamble(self, n_words: int) -> str:
        """A preamble large enough to push the heuristic past its thresholds."""
        # Use varied vocab so token count is realistic (cl100k_base on Greek)
        words = ["διάταξις", "νόμος", "παράγραφος", "ορίζεται", "κανονισμός"]
        return " ".join(words[i % len(words)] for i in range(n_words))

    def test_large_preamble_one_article_uses_sliding_window(self):
        """12 pages of preamble + 1 small article → sliding window, preamble preserved."""
        # ~2500 words of preamble — easily above the 4000-token guard.
        # Article 1 appears at the very end with tiny content.
        preamble = self._make_preamble(2500)
        text = preamble + "\n\nΆρθρο 1\n\nΣύντομη διάταξη του άρθρου."
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc("PD-24-like.pdf"))

        # Fallback path: every chunk has article=None (no per-article labels)
        assert all(c.article is None for c in chunks), (
            "expected sliding-window chunks (article=None), got: "
            f"{[c.article for c in chunks]}"
        )

        # The preamble text MUST appear somewhere in the chunks
        joined = " ".join(c.text for c in chunks)
        assert "διάταξις" in joined, "preamble content was dropped — fallback failed"
        assert "Σύντομη διάταξη" in joined, "article body should also be present"

    def test_first_article_past_30_percent_triggers_fallback(self):
        """Doc where the first article is past 30% of total length → fallback."""
        preamble = self._make_preamble(2000)  # ~big preamble
        body = self._make_preamble(800) + "\n\nΆρθρο 1\n\nΔιάταξη."
        text = preamble + "\n\n" + body
        # preamble (2000 words) is ~70%+ of doc; first article is past 30%
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc("preamble-heavy.pdf"))

        # All chunks should be article=None (fallback path)
        assert all(c.article is None for c in chunks)
        joined = " ".join(c.text for c in chunks)
        assert "διάταξις" in joined  # preamble preserved

    def test_well_structured_doc_uses_article_based(self):
        """Many articles starting near the top → article-based chunking (unchanged)."""
        sections = []
        for n in range(1, 21):  # 20 articles
            sections.append(f"Άρθρο {n}\n" + self._make_preamble(40))
        text = "\n\n".join(sections)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc("well-formed-law.pdf"))

        # Article-based path: chunks carry their article labels
        article_labels = {c.article for c in chunks}
        # At least some of the 20 articles should be present as labels
        assert any(label and label.startswith("Άρθρο") for label in article_labels), (
            f"expected article labels, got: {article_labels}"
        )
        # None of the chunks should be article=None (that would mean fallback)
        assert None not in article_labels

    def test_below_min_tokens_guard_uses_article_based(self):
        """Tiny doc with 1 article → article-based (heuristic guard prevents fallback)."""
        text = "Άρθρο 1\n\n" + _word_repeat(50)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc())
        # Tiny doc; preamble heuristic doesn't apply → keeps article label
        assert chunks[0].article == "Άρθρο 1"

    def test_no_articles_still_uses_sliding_window(self):
        """Existing behavior: zero articles always uses sliding window."""
        text = self._make_preamble(50)  # plain text, no Άρθρο markers
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc("no-articles.pdf"))
        assert all(c.article is None for c in chunks)

    def test_few_articles_in_substantial_doc_triggers_fallback(self):
        """≥4000-token doc with only 1 article → fallback (low article density)."""
        # Single article but the whole document is only 1 article long across
        # ~5000 tokens.  Article starts at position 0 so preamble is 0%, but
        # the n_articles<3 condition still fires above the size guard.
        text = "Άρθρο 1\n\n" + self._make_preamble(5000)
        pages = [_page(text)]
        chunks = chunk_pages(pages, _doc("sparse-articles.pdf"))
        # Fallback: chunks have no article label
        assert all(c.article is None for c in chunks)


class TestFallbackDecisionLogic:
    """Direct tests for the _decide_chunking_path helper."""

    def test_no_articles_always_falls_back(self):
        from src.ingestion.chunker import _decide_chunking_path
        use_fb, reason = _decide_chunking_path("some text", articles=[], total_tokens=50)
        assert use_fb
        assert "no articles" in reason

    def test_small_doc_with_one_article_does_not_fall_back(self):
        from src.ingestion.chunker import _decide_chunking_path
        # Below the 4000-token guard
        use_fb, _ = _decide_chunking_path(
            "Άρθρο 1\n\nshort", articles=[(0, "Άρθρο 1")], total_tokens=100,
        )
        assert not use_fb

    def test_large_doc_with_30_percent_preamble_falls_back(self):
        from src.ingestion.chunker import _decide_chunking_path
        # ≥3 articles (so "few articles" check doesn't fire) but article 1 is
        # at position 400/1000 = 40% → preamble check triggers
        full_text = "x" * 1000
        articles = [(400, "Άρθρο 1"), (600, "Άρθρο 2"), (800, "Άρθρο 3")]
        use_fb, reason = _decide_chunking_path(full_text, articles, total_tokens=5000)
        assert use_fb
        assert "30%" in reason or "40%" in reason

    def test_large_doc_with_5_percent_preamble_does_not_fall_back(self):
        from src.ingestion.chunker import _decide_chunking_path
        # Article 1 at position 50 of 1000 = 5% preamble, ≥3 articles
        full_text = "x" * 1000
        articles = [(50, "Άρθρο 1"), (300, "Άρθρο 2"), (600, "Άρθρο 3")]
        use_fb, _ = _decide_chunking_path(full_text, articles, total_tokens=5000)
        assert not use_fb

    def test_large_doc_with_few_articles_falls_back(self):
        from src.ingestion.chunker import _decide_chunking_path
        # 1 article, low preamble — fails the "< 3 articles" check
        use_fb, reason = _decide_chunking_path(
            "x" * 1000, articles=[(0, "Άρθρο 1")], total_tokens=5000,
        )
        assert use_fb
        assert "articles" in reason

    def test_at_30_percent_boundary_just_below_does_not_trigger(self):
        from src.ingestion.chunker import _decide_chunking_path
        # preamble exactly 30% → uses strict `>` so does NOT trigger
        full_text = "x" * 1000
        articles = [(300, "Άρθρο 1"), (500, "Άρθρο 2"), (800, "Άρθρο 3")]
        use_fb, _ = _decide_chunking_path(full_text, articles, total_tokens=5000)
        assert not use_fb

    def test_at_30_percent_boundary_just_above_triggers(self):
        from src.ingestion.chunker import _decide_chunking_path
        full_text = "x" * 1000
        articles = [(301, "Άρθρο 1"), (500, "Άρθρο 2"), (800, "Άρθρο 3")]
        use_fb, reason = _decide_chunking_path(full_text, articles, total_tokens=5000)
        assert use_fb
        assert "30%" in reason or "40%" in reason

    def test_at_40_percent_boundary_just_above_triggers(self):
        from src.ingestion.chunker import _decide_chunking_path
        full_text = "x" * 1000
        # 401/1000 = 40.1% → triggers the 30% threshold first (still correct)
        articles = [(401, "Άρθρο 1"), (600, "Άρθρο 2"), (800, "Άρθρο 3")]
        use_fb, _ = _decide_chunking_path(full_text, articles, total_tokens=5000)
        assert use_fb
