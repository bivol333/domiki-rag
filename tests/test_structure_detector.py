"""Tests for structure_detector — Greek regex edge cases."""

from src.ingestion.structure_detector import (
    extract_fek_refs,
    extract_law_refs,
    find_articles,
    find_paragraphs,
)


class TestFindArticles:
    def test_standard_article(self):
        text = "Άρθρο 23\n\nΚείμενο άρθρου."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 23"

    def test_article_with_letter_suffix(self):
        text = "Άρθρο 23α\n\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 23α"

    def test_multiple_articles(self):
        text = "Άρθρο 1\n\nΚείμενο.\n\nΆρθρο 2\n\nΑλλο κείμενο."
        results = find_articles(text)
        assert len(results) == 2
        assert results[0][1] == "Άρθρο 1"
        assert results[1][1] == "Άρθρο 2"

    def test_article_mid_sentence_no_match(self):
        """'άρθρο' mid-sentence (lowercase, no line-start) must NOT match."""
        text = "Σύμφωνα με το άρθρο 10 του νόμου..."
        results = find_articles(text)
        assert results == []

    def test_article_with_leading_whitespace(self):
        text = "   Άρθρο 5\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"


class TestFindParagraphs:
    def test_numbered_dot_form(self):
        text = "1. Πρώτη παράγραφος.\n2. Δεύτερη παράγραφος."
        results = find_paragraphs(text)
        assert any(r[1] == "παρ. 1" for r in results)
        assert any(r[1] == "παρ. 2" for r in results)

    def test_par_abbreviation(self):
        text = "παρ. 4 ορίζεται ότι..."
        results = find_paragraphs(text)
        assert any(r[1] == "παρ. 4" for r in results)

    def test_paragrafos_full_word(self):
        text = "παράγραφος 4 ορίζει..."
        results = find_paragraphs(text)
        assert any(r[1] == "παρ. 4" for r in results)


class TestExtractFekRefs:
    def test_standard_fek(self):
        text = "ΦΕΚ Α' 167/2017"
        refs = extract_fek_refs(text)
        assert len(refs) == 1
        assert "167" in refs[0]
        assert "2017" in refs[0]

    def test_fek_with_dots(self):
        text = "Φ.Ε.Κ. Α 167/17"
        refs = extract_fek_refs(text)
        assert len(refs) == 1
        assert "167" in refs[0]

    def test_multiple_fek_refs(self):
        text = "ΦΕΚ Α' 100/2010 και ΦΕΚ Β' 200/2020"
        refs = extract_fek_refs(text)
        assert len(refs) == 2


class TestExtractLawRefs:
    def test_law_number(self):
        text = "Ν. 4495/2017"
        refs = extract_law_refs(text)
        assert len(refs) >= 1
        assert "4495" in refs[0]
        assert "2017" in refs[0]

    def test_nomos_full_word(self):
        text = "Νόμος 4495/2017"
        refs = extract_law_refs(text)
        assert len(refs) >= 1
        assert "4495" in refs[0]

    def test_presidential_decree(self):
        text = "Π.Δ. 696/74"
        refs = extract_law_refs(text)
        assert len(refs) >= 1
        assert "696" in refs[0]

    def test_no_false_positives(self):
        """Numbers without law prefix should not match."""
        text = "Στοιχεία: 1234/2020 αριθμός"
        refs = extract_law_refs(text)
        assert refs == []
