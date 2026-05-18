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
