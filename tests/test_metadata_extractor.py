"""Tests for metadata_extractor."""
from datetime import date

from src.ingestion.metadata_extractor import extract_metadata
from src.ingestion.pdf_parser import PageContent


def _make_page(text: str, num: int = 1) -> PageContent:
    return PageContent(page_number=num, text=text, has_tables=False)


class TestExtractMetadata:
    def test_extracts_law_number(self):
        pages = [_make_page("Ν. 4495/2017\nΚΑΝΟΝΙΣΜΟΣ ΔΟΜΗΣΗΣ")]
        meta = extract_metadata(pages, "N_4495_2017.pdf", "public")
        assert meta.law_number is not None
        assert "4495" in meta.law_number
        assert "2017" in meta.law_number

    def test_extracts_fek_ref(self):
        pages = [_make_page("ΦΕΚ Α' 232/2017\nΠεριεχόμενο νόμου")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.fek_ref is not None
        assert "232" in meta.fek_ref

    def test_extracts_greek_date(self):
        pages = [_make_page("Αθήνα, 5 Νοεμβρίου 2017\nΈναρξη ισχύος")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.issue_date == date(2017, 11, 5)

    def test_extracts_title_from_first_line(self):
        pages = [_make_page("ΚΑΝΟΝΙΣΜΟΣ ΔΟΜΗΣΗΣ ΚΑΙ ΠΟΛΕΟΔΟΜΙΑΣ\nΆρθρο 1")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.title is not None
        assert "ΚΑΝΟΝΙΣΜΟΣ" in meta.title

    def test_missing_fields_are_none(self):
        pages = [_make_page("Απλό κείμενο χωρίς μεταδεδομένα")]
        meta = extract_metadata(pages, "unknown.pdf", "public")
        assert meta.law_number is None
        assert meta.fek_ref is None
        assert meta.issue_date is None

    def test_source_type_inferred_from_filename(self):
        pages = [_make_page("ΦΕΚ ΤΕΥΧΟΣ ΠΡΩΤΟ")]
        meta = extract_metadata(pages, "FEK_A_167_2017.pdf", "public")
        assert meta.source_type == "fek"

    def test_scope_preserved(self):
        pages = [_make_page("Κείμενο")]
        meta = extract_metadata(pages, "test.pdf", "private")
        assert meta.scope == "private"

    def test_total_pages(self):
        pages = [_make_page("Σελίδα 1", 1), _make_page("Σελίδα 2", 2)]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.total_pages == 2

    def test_court_decision_from_content(self):
        pages = [_make_page("ΣΥΜΒΟΥΛΙΟ ΤΗΣ ΕΠΙΚΡΑΤΕΙΑΣ\nΑπόφαση 1234/2020")]
        meta = extract_metadata(pages, "decision.pdf", "public")
        assert meta.issuing_body == "ΣτΕ"


class TestLawNumberBugFixes:
    # Bug 1: duplication from no-space form "Ν.4495/2017"
    def test_no_law_number_duplication(self):
        pages = [_make_page("Ν.4495/2017\nΚείμενο")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.law_number is not None
        assert meta.law_number.count("4495") == 1

    # Bug 3: canonical format regardless of source form
    def test_canonical_law_format_no_space(self):
        pages = [_make_page("Ν.4495/2017\nΚείμενο")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.law_number == "Ν. 4495/2017"

    def test_canonical_law_format_lowercase(self):
        pages = [_make_page("ν. 4495/2017\nΚείμενο")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.law_number == "Ν. 4495/2017"

    def test_canonical_law_format_full_word(self):
        pages = [_make_page("Νόμος 4495/2017\nΚείμενο")]
        meta = extract_metadata(pages, "test.pdf", "public")
        assert meta.law_number == "Ν. 4495/2017"

    # Bug 2: primary law = most frequent across full document
    def test_primary_law_is_most_frequent_not_first(self):
        page1 = _make_page("Ν. 3852/2010 αναφέρεται εδώ\nΚείμενο σελίδας 1", 1)
        # 4495/2017 appears 5 times on page 2 vs 3852/2010 once on page 1
        page2 = _make_page(
            "Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017",
            2,
        )
        meta = extract_metadata(pages=[page1, page2], source_file="egkyklios.pdf", scope="public")
        assert meta.law_number is not None
        assert "4495" in meta.law_number
        assert "3852" not in meta.law_number


class TestTitleBugFixes:
    # Bug 4: prefer "Θέμα:" line over short header label
    def test_title_from_thema_line(self):
        text = (
            "ΕΓΚΥΚΛΙΟΣ 2\n"
            "Θέμα: Διευκρινίσεις διατάξεων του τμήματος Δ' του ν.4495/2017\n\n"
            "Κύριε Διευθυντά..."
        )
        meta = extract_metadata(pages=[_make_page(text)], source_file="egk.pdf", scope="public")
        assert meta.title is not None
        assert "Διευκρινίσεις" in meta.title

    def test_title_skips_short_header_labels(self):
        # "ΕΓΚΥΚΛΙΟΣ 2" is 12 chars — below the 20-char threshold; should not be title
        text = "ΕΓΚΥΚΛΙΟΣ 2\nΔιευκρινίσεις επί των διατάξεων του νόμου περί δόμησης"
        meta = extract_metadata(pages=[_make_page(text)], source_file="egk.pdf", scope="public")
        assert meta.title is not None
        assert "Διευκρινίσεις" in meta.title
