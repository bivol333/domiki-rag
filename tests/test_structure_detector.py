"""Tests for structure_detector — Greek regex edge cases."""

from src.ingestion.structure_detector import (
    _ordinal_to_int,
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


class TestFindArticlesExpanded:
    """Additional article-heading variants required for Phase 4d."""

    # ── Καθαρεύουσα ──────────────────────────────────────────────────────────
    def test_katharevousa_arthron(self):
        text = "Άρθρον 5\n\nΚείμενο άρθρου."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"

    # ── Uppercase ─────────────────────────────────────────────────────────────
    def test_uppercase_arthro(self):
        text = "ΑΡΘΡΟ 5\n\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"

    def test_uppercase_arthron(self):
        text = "ΑΡΘΡΟΝ 10\n\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 10"

    # ── Abbreviations ─────────────────────────────────────────────────────────
    def test_abbreviation_arth_dot(self):
        text = "Άρθ. 5\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"

    def test_abbreviation_arthr_dot(self):
        text = "Αρθρ. 5\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"

    def test_abbreviation_arth_dot_uppercase(self):
        text = "ΑΡΘ. 5\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 5"

    # ── Letter suffix ─────────────────────────────────────────────────────────
    def test_article_with_uppercase_letter_suffix(self):
        text = "Άρθρο 5Α\n\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        # Label preserves original suffix
        assert "5" in results[0][1]

    # ── Mixed corpus regression ────────────────────────────────────────────────
    def test_mixed_corpus_all_variants(self):
        text = (
            "Άρθρο 1\nΚείμενο α.\n\n"
            "Άρθρον 2\nΚείμενο β.\n\n"
            "ΑΡΘΡΟ 3\nΚείμενο γ.\n\n"
            "Άρθ. 4\nΚείμενο δ."
        )
        results = find_articles(text)
        assert len(results) == 4
        numbers = [r[1].split()[-1] for r in results]
        assert numbers == ["1", "2", "3", "4"]

    # ── No-tonos form ─────────────────────────────────────────────────────────
    def test_no_tonos_arthro(self):
        """'Αρθρο' (without accent) must still be detected."""
        text = "Αρθρο 7\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 7"


class TestWordOrdinalArticles:
    """Word-ordinal article headings (Phase 4d Addition 1)."""

    def test_proton_maps_to_1(self):
        text = "Άρθρο Πρώτο\nΕισαγωγικές διατάξεις."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 1"

    def test_deftero_maps_to_2(self):
        text = "Άρθρο Δεύτερο\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 2"

    def test_trito_maps_to_3(self):
        text = "Άρθρο Τρίτο\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 3"

    def test_tetarto_maps_to_4(self):
        results = find_articles("Άρθρο Τέταρτο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 4"

    def test_pempto_maps_to_5(self):
        results = find_articles("Άρθρο Πέμπτο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 5"

    def test_ekto_maps_to_6(self):
        results = find_articles("Άρθρο Έκτο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 6"

    def test_ebdomo_maps_to_7(self):
        results = find_articles("Άρθρο Έβδομο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 7"

    def test_ogdoo_maps_to_8(self):
        results = find_articles("Άρθρο Όγδοο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 8"

    def test_enato_maps_to_9(self):
        results = find_articles("Άρθρο Ένατο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 9"

    def test_dekato_maps_to_10(self):
        results = find_articles("Άρθρο Δέκατο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 10"

    def test_endekato_maps_to_11(self):
        results = find_articles("Άρθρο Ενδέκατο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 11"

    def test_dodekato_maps_to_12(self):
        results = find_articles("Άρθρο Δωδέκατο\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 12"

    def test_eikosto_maps_to_20(self):
        results = find_articles("Άρθρο Εικοστό\nΚείμενο.")
        assert results and results[0][1] == "Άρθρο 20"

    def test_uppercase_proton(self):
        """ΑΡΘΡΟ ΠΡΩΤΟ must be detected (all-caps, no tonos)."""
        text = "ΑΡΘΡΟ ΠΡΩΤΟ\nΕισαγωγικές διατάξεις."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 1"

    def test_proton_with_suffix_n(self):
        """'Πρώτον' (καθαρεύουσα nominative) also maps to 1."""
        text = "Άρθρον Πρώτον\nΔιατάξεις."
        results = find_articles(text)
        assert len(results) == 1
        assert results[0][1] == "Άρθρο 1"

    def test_ordinal_sorted_with_digit_articles(self):
        """Ordinal and digit articles appear in position order."""
        text = "Άρθρο Πρώτο\nΕισαγωγή.\n\nΆρθρο 2\nΚείμενο."
        results = find_articles(text)
        assert len(results) == 2
        assert results[0][1] == "Άρθρο 1"
        assert results[1][1] == "Άρθρο 2"

    def test_mid_sentence_ordinal_no_match(self):
        """'Πρώτο' mid-sentence must not match."""
        text = "Η πρώτο διάταξη ορίζει ότι..."
        results = find_articles(text)
        assert results == []


class TestOrdinalToInt:
    def test_known_ordinals(self):
        pairs = [
            ("Πρώτο", 1), ("Δεύτερο", 2), ("Τρίτο", 3), ("Τέταρτο", 4),
            ("Πέμπτο", 5), ("Έκτο", 6), ("Έβδομο", 7), ("Όγδοο", 8),
            ("Ένατο", 9), ("Δέκατο", 10), ("Ενδέκατο", 11), ("Δωδέκατο", 12),
            ("Εικοστό", 20),
        ]
        for word, expected in pairs:
            assert _ordinal_to_int(word) == expected, f"Failed for {word!r}"

    def test_uppercase_forms(self):
        assert _ordinal_to_int("ΠΡΩΤΟ") == 1
        assert _ordinal_to_int("ΔΕΥΤΕΡΟ") == 2

    def test_katharevousa_form(self):
        assert _ordinal_to_int("Πρώτον") == 1

    def test_unknown_word_returns_none(self):
        assert _ordinal_to_int("Κείμενο") is None
        assert _ordinal_to_int("5") is None
        assert _ordinal_to_int("") is None


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
