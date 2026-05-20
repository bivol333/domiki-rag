"""Tests for text_cleaner — conservative webpage noise removal."""
import unicodedata

from src.ingestion.text_cleaner import _is_chrome_line, clean_legal_text


class TestPuaGlyphs:
    def test_pua_glyphs_removed(self):
        # U+F0E1, U+F073 are icon-font chars from e-nomothesia.gr page headers
        text = "Άρθρο 1" + chr(0xF0E1) + chr(0xF073) + " Κείμενο"
        result = clean_legal_text(text, "test.pdf")
        assert chr(0xF0E1) not in result
        assert chr(0xF073) not in result
        assert "Κείμενο" in result

    def test_pua_glyphs_multiple_types(self):
        # Several icon-font chars from the diagnosed PDF
        icons = "".join(chr(c) for c in [0xF0E1, 0xF073, 0xF080, 0xF35D, 0xF15C])
        text = "Άρθρο 1\n" + icons + "\nΚείμενο"
        result = clean_legal_text(text)
        for c in [0xF0E1, 0xF073, 0xF080, 0xF35D, 0xF15C]:
            assert chr(c) not in result
        assert "Κείμενο" in result

    def test_legal_text_preserved_around_pua(self):
        text = "παρ. 5" + chr(0xF099) + "Επιτρέπεται η ανέγερση"
        result = clean_legal_text(text)
        assert "παρ. 5" in result
        assert "Επιτρέπεται" in result


class TestWhitespaceNormalization:
    def test_nbsp_normalized_to_space(self):
        text = "Κείμενο\xa0νόμου\xa0περί\xa0δόμησης"
        result = clean_legal_text(text)
        assert "\xa0" not in result
        assert "Κείμενο νόμου περί δόμησης" in result

    def test_multiple_spaces_collapsed(self):
        text = "Άρθρο 1\n\nΚείμενο    με    πολλά    κενά"
        result = clean_legal_text(text)
        assert "  " not in result  # no double spaces
        assert "Κείμενο με πολλά κενά" in result

    def test_paragraph_breaks_preserved(self):
        text = "Άρθρο 1\n\nΠρώτη παράγραφος.\n\nΔεύτερη παράγραφος."
        result = clean_legal_text(text)
        assert "\n\n" in result  # paragraph structure preserved

    def test_nfc_normalization_applied(self):
        # 'ά' in NFD form = 'α' + combining tonos (2 codepoints)
        nfd_text = unicodedata.normalize("NFD", "Άρθρο 5 — Γενικές Διατάξεις")
        assert not unicodedata.is_normalized("NFC", nfd_text)
        result = clean_legal_text(nfd_text)
        assert unicodedata.is_normalized("NFC", result)

    def test_tabs_collapsed_to_space(self):
        text = "Άρθρο\t5\t\tΚείμενο"
        result = clean_legal_text(text)
        assert "\t" not in result


class TestChromeLinesRemoved:
    def test_syndesee_standalone_removed(self):
        text = "Άρθρο 1\nΣύνδεση\nΚείμενο άρθρου"
        result = clean_legal_text(text)
        # The standalone navigation line must be gone
        result_lines = [ln.strip() for ln in result.split("\n")]
        assert "Σύνδεση" not in result_lines

    def test_syndromitikes_removed(self):
        text = "Κείμενο\nΣυνδρομητικές Υπηρεσίες\nΆρθρο 2"
        result = clean_legal_text(text)
        assert "Συνδρομητικές Υπηρεσίες" not in result

    def test_syndromitikes_with_suffix_removed(self):
        text = "Κείμενο\nΣυνδρομητικές Υπηρεσίες e-nomothesia\nΆρθρο 2"
        result = clean_legal_text(text)
        assert "Συνδρομητικές" not in result

    def test_trapeza_pliroforion_removed(self):
        text = "Άρθρο 1\nΤράπεζα Πληροφοριών\nΚείμενο"
        result = clean_legal_text(text)
        result_lines = [ln.strip() for ln in result.split("\n")]
        assert "Τράπεζα Πληροφοριών" not in result_lines

    def test_enomothesia_standalone_removed(self):
        text = "Άρθρο 1\ne-nomothesia.gr\nΚείμενο"
        result = clean_legal_text(text)
        result_lines = [ln.strip() for ln in result.split("\n")]
        assert "e-nomothesia.gr" not in result_lines

    def test_navigation_lines_removed(self):
        text = "Άρθρο 1\nΕπόμενο άρθρο\nΠροηγούμενο άρθρο\nΚείμενο"
        result = clean_legal_text(text)
        assert "Επόμενο άρθρο" not in result
        assert "Προηγούμενο άρθρο" not in result
        assert "Κείμενο" in result


class TestConservatism:
    def test_syndesee_in_legal_sentence_preserved(self):
        """'σύνδεση' inside a real legal sentence must NOT be removed."""
        text = "Η σύνδεση του ακινήτου με το δίκτυο ύδρευσης είναι υποχρεωτική."
        result = clean_legal_text(text)
        assert "σύνδεση" in result

    def test_url_in_legal_sentence_preserved(self):
        """A URL cited within a sentence (not a standalone footer) must be kept."""
        text = "Βλ. https://www.e-nomothesia.gr/kat-demo/test.html για λεπτομέρειες."
        result = clean_legal_text(text)
        assert "e-nomothesia.gr" in result

    def test_standalone_url_removed(self):
        """A line that is ONLY a URL is a page footer and must be removed."""
        text = "Άρθρο 1\nhttps://www.e-nomothesia.gr/kat-pyroprostasia/pd-41-2018.html\nΚείμενο"
        result = clean_legal_text(text)
        assert "e-nomothesia.gr" not in result
        assert "Κείμενο" in result

    def test_real_legal_text_not_stripped(self):
        """A full article of legal prose must pass through unchanged (modulo whitespace)."""
        legal = (
            "Άρθρο 3\n\n"
            "Για την έκδοση οικοδομικής άδειας απαιτείται η υποβολή τοπογραφικού "
            "διαγράμματος, αρχιτεκτονικών σχεδίων και στατικής μελέτης.\n\n"
            "παρ. 2\nΗ αίτηση υποβάλλεται στην αρμόδια Υπηρεσία Δόμησης."
        )
        result = clean_legal_text(legal)
        assert "Άρθρο 3" in result
        assert "οικοδομικής άδειας" in result
        assert "Υπηρεσία Δόμησης" in result

    def test_empty_text_returns_empty(self):
        assert clean_legal_text("") == ""

    def test_whitespace_only_returns_empty(self):
        assert clean_legal_text("   \n\n\t  ") == ""


class TestIsChromeLine:
    def test_exact_syndesee(self):
        assert _is_chrome_line("Σύνδεση") is True

    def test_syndesee_with_more_words(self):
        # "Σύνδεση" is exact-match only — more words → NOT chrome
        assert _is_chrome_line("Σύνδεση με το δίκτυο") is False

    def test_syndromitikes_prefix(self):
        assert _is_chrome_line("Συνδρομητικές Υπηρεσίες") is True
        assert _is_chrome_line("Συνδρομητικές Υπηρεσίες | Επικοινωνία") is True

    def test_blank_line_not_chrome(self):
        assert _is_chrome_line("") is False
        assert _is_chrome_line("   ") is False

    def test_case_insensitive(self):
        assert _is_chrome_line("ΣΥΝΔΕΣΗ") is True
        assert _is_chrome_line("σύνδεση") is True
