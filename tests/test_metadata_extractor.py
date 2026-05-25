"""Tests for metadata_extractor."""
from datetime import date

from src.ingestion.metadata_extractor import (
    _law_ref_from_filename,
    _law_ref_from_ya_kya_filename,
    extract_metadata,
)
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


class TestFilenameBasedLawExtraction:
    """Filename-first law number extraction (Phase 4d Addition 2)."""

    def test_pd_hyphen_filename(self):
        assert _law_ref_from_filename("PD-41-2018-Pyroprostasia.pdf") == "Π.Δ. 41/2018"

    def test_n_hyphen_filename(self):
        assert _law_ref_from_filename("N4178-2013-Old-Authaireta.pdf") == "Ν. 4178/2013"

    def test_n_no_separator_filename(self):
        assert _law_ref_from_filename("n44952017-demo.pdf") == "Ν. 4495/2017"

    def test_n_underscore_filename(self):
        assert _law_ref_from_filename("N_4495_2017.pdf") == "Ν. 4495/2017"

    def test_unknown_filename_returns_none(self):
        assert _law_ref_from_filename("egkyklios.pdf") is None
        assert _law_ref_from_filename("document.pdf") is None

    def test_pd41_law_number_wins_over_body_cross_refs(self):
        """Filename extraction must win even when body text has many cross-references."""
        # Body text has Π.Δ. 71/1988 repeated 10 times — the old bug
        body = "Π.Δ. 71/1988 " * 10
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "PD-41-2018-Pyroprostasia.pdf", "public")
        assert meta.law_number == "Π.Δ. 41/2018"

    def test_n4178_law_number_wins_over_body_cross_refs(self):
        body = "Ν. 998/1979 " * 10  # older cross-referenced law
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "N4178-2013-Old-Test.pdf", "public")
        assert meta.law_number == "Ν. 4178/2013"

    def test_circular_without_law_in_filename_uses_frequency(self):
        """Circulars (egkyklios.pdf) have no law in filename → frequency fallback."""
        page1 = _make_page("Ν. 3852/2010 αναφέρεται εδώ\nΚείμενο σελίδας 1", 1)
        page2 = _make_page(
            "Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017 Ν. 4495/2017",
            2,
        )
        meta = extract_metadata([page1, page2], "egkyklios.pdf", "public")
        assert meta.law_number is not None
        assert "4495" in meta.law_number


class TestSourceTypeFixes:
    """Source type classification fixes (Phase 4d Addition 2)."""

    def test_pd_hyphen_filename_is_presidential_decree(self):
        """PD-41-2018 must be presidential_decree even when body has ΣτΕ."""
        pages = [_make_page("ΣτΕ 1234/2000 αναφέρεται ως παράδειγμα")]
        meta = extract_metadata(pages, "PD-41-2018-Pyroprostasia.pdf", "public")
        assert meta.source_type == "presidential_decree"

    def test_pd_uppercase_filename_is_presidential_decree(self):
        pages = [_make_page("Κείμενο")]
        meta = extract_metadata(pages, "PD-41-2018.pdf", "public")
        assert meta.source_type == "presidential_decree"

    def test_fek_filename_still_fek(self):
        pages = [_make_page("ΦΕΚ ΤΕΥΧΟΣ ΠΡΩΤΟ")]
        meta = extract_metadata(pages, "FEK_A_167_2017.pdf", "public")
        assert meta.source_type == "fek"

    def test_ste_content_is_court_decision_when_filename_unknown(self):
        pages = [_make_page("ΣΥΜΒΟΥΛΙΟ ΤΗΣ ΕΠΙΚΡΑΤΕΙΑΣ\nΑπόφαση 1234/2020")]
        meta = extract_metadata(pages, "decision.pdf", "public")
        assert meta.source_type == "court_decision"

    def test_presidential_decree_in_content_when_filename_unknown(self):
        pages = [_make_page("ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ ΥΠ ΑΡΙΘΜ. 100")]
        meta = extract_metadata(pages, "document.pdf", "public")
        assert meta.source_type == "presidential_decree"


class TestOnDiskFilenames:
    """Regression tests using the exact filenames from data/raw_pdfs/public/.

    These guard against regressions in filename-based law/type extraction
    for every PDF currently in the corpus.
    """

    # ── Law numbers ──────────────────────────────────────────────────────────

    def test_n1577_law_number(self):
        pages = [_make_page("Ν. 1577/1985 ΓΟΚ")]
        meta = extract_metadata(pages, "N1577-1985-Old-GOK-Codified.pdf", "public")
        assert meta.law_number == "Ν. 1577/1985"

    def test_n2971_law_number(self):
        pages = [_make_page("Ν. 2971/2001 Αιγιαλός")]
        meta = extract_metadata(pages, "N2971-2001-Aigialos-Codified-202501.pdf", "public")
        assert meta.law_number == "Ν. 2971/2001"

    def test_n4067_law_number(self):
        pages = [_make_page("Ν. 4067/2012 ΝΟΚ")]
        meta = extract_metadata(pages, "N4067-2012-NOK-Codified-202512.pdf", "public")
        assert meta.law_number == "Ν. 4067/2012"

    def test_n4178_law_number(self):
        # Body text has many cross-references — filename must win
        body = "Ν. 998/1979 " * 8
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "N4178-2013-Old-Authaireta-Codified-202512.pdf", "public")
        assert meta.law_number == "Ν. 4178/2013"

    def test_n4495_no_separator_law_number(self):
        pages = [_make_page("Ν. 4495/2017")]
        meta = extract_metadata(pages, "n44952017-demo.pdf", "public")
        assert meta.law_number == "Ν. 4495/2017"

    def test_n4858_law_number(self):
        pages = [_make_page("Ν. 4858/2021")]
        meta = extract_metadata(pages, "N4858-2021-Arxaiologikos-Codified-202601.pdf", "public")
        assert meta.law_number == "Ν. 4858/2021"

    def test_n998_law_number(self):
        pages = [_make_page("Ν. 998/1979 Δασικός")]
        meta = extract_metadata(pages, "N998-1979-Dasikos-Codified-202507.pdf", "public")
        assert meta.law_number == "Ν. 998/1979"

    def test_pd24_law_number(self):
        # Body text may reference other laws — filename must win
        body = "Ν. 3212/2003 " * 10
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "PD-24-1985-Ektos-Sxediou.pdf", "public")
        assert meta.law_number == "Π.Δ. 24/1985"

    def test_pd41_law_number(self):
        body = "Π.Δ. 71/1988 " * 10
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "PD-41-2018-Pyroprostasia.pdf", "public")
        assert meta.law_number == "Π.Δ. 41/2018"

    # ── Source types ─────────────────────────────────────────────────────────

    def test_n1577_source_type_is_law(self):
        pages = [_make_page("Ν. 1577/1985")]
        meta = extract_metadata(pages, "N1577-1985-Old-GOK-Codified.pdf", "public")
        assert meta.source_type == "law"

    def test_n2971_source_type_is_law(self):
        pages = [_make_page("Ν. 2971/2001")]
        meta = extract_metadata(pages, "N2971-2001-Aigialos-Codified-202501.pdf", "public")
        assert meta.source_type == "law"

    def test_n4067_source_type_is_law(self):
        pages = [_make_page("Ν. 4067/2012")]
        meta = extract_metadata(pages, "N4067-2012-NOK-Codified-202512.pdf", "public")
        assert meta.source_type == "law"

    def test_n4178_source_type_is_law(self):
        pages = [_make_page("Ν. 4178/2013")]
        meta = extract_metadata(pages, "N4178-2013-Old-Authaireta-Codified-202512.pdf", "public")
        assert meta.source_type == "law"

    def test_n4495_source_type_is_law(self):
        pages = [_make_page("Ν. 4495/2017")]
        meta = extract_metadata(pages, "n44952017-demo.pdf", "public")
        assert meta.source_type == "law"

    def test_n4858_source_type_is_law(self):
        pages = [_make_page("Ν. 4858/2021")]
        meta = extract_metadata(pages, "N4858-2021-Arxaiologikos-Codified-202601.pdf", "public")
        assert meta.source_type == "law"

    def test_n998_source_type_is_law(self):
        pages = [_make_page("Ν. 998/1979")]
        meta = extract_metadata(pages, "N998-1979-Dasikos-Codified-202507.pdf", "public")
        assert meta.source_type == "law"

    def test_pd24_source_type_is_presidential_decree(self):
        # Must NOT be classified as court_decision even if body has ΣτΕ references
        pages = [_make_page("ΣτΕ 100/2000 αναφέρεται")]
        meta = extract_metadata(pages, "PD-24-1985-Ektos-Sxediou.pdf", "public")
        assert meta.source_type == "presidential_decree"

    def test_pd41_source_type_is_presidential_decree(self):
        pages = [_make_page("ΣτΕ 1234/2000 αναφέρεται")]
        meta = extract_metadata(pages, "PD-41-2018-Pyroprostasia.pdf", "public")
        assert meta.source_type == "presidential_decree"

    def test_egkyklios_source_type_is_circular(self):
        pages = [_make_page("Εγκύκλιος")]
        meta = extract_metadata(pages, "Egkyklios_4495_2017.pdf", "public")
        assert meta.source_type == "circular"


class TestYAKYAMetadata:
    """YA / KYA files must never inherit a referenced law's number (Phase 4d v7)."""

    def test_ya_law_number_not_cross_reference(self):
        """The body repeatedly mentions Ν. 4495/2017 — must NOT become the law_number."""
        body = "Σε εφαρμογή του Ν. 4495/2017 περί δόμησης. " * 10
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "YA-Ktiriodomikos-2023.pdf", "public")
        assert meta.law_number != "Ν. 4495/2017"

    def test_ya_law_number_derived_from_filename(self):
        """law_number for YA file contains the filename descriptive tokens."""
        pages = [_make_page("")]
        meta = extract_metadata(pages, "YA-Ktiriodomikos-2023.pdf", "public")
        assert meta.law_number is not None
        assert "2023" in meta.law_number

    def test_ya_source_type_is_ministerial_decision(self):
        """YA filename prefix → source_type ministerial_decision from filename rule."""
        pages = [_make_page("")]
        meta = extract_metadata(pages, "YA-Ktiriodomikos-2023.pdf", "public")
        assert meta.source_type == "ministerial_decision"

    def test_kya_law_number_not_cross_reference(self):
        body = "Ν. 4495/2017 " * 5
        pages = [_make_page(body)]
        meta = extract_metadata(pages, "KYA-SomeLaw-2020.pdf", "public")
        assert meta.law_number != "Ν. 4495/2017"

    def test_kya_source_type_is_ministerial_decision(self):
        pages = [_make_page("")]
        meta = extract_metadata(pages, "KYA-SomeLaw-2020.pdf", "public")
        assert meta.source_type == "ministerial_decision"

    def test_law_ref_from_ya_kya_filename_ya(self):
        result = _law_ref_from_ya_kya_filename("YA-Ktiriodomikos-2023.pdf")
        assert result == "ΥΑ Ktiriodomikos 2023"

    def test_law_ref_from_ya_kya_filename_kya(self):
        result = _law_ref_from_ya_kya_filename("KYA-Diagonismos-2021.pdf")
        assert result == "ΚΥΑ Diagonismos 2021"

    def test_law_ref_from_ya_kya_filename_non_ya_returns_none(self):
        assert _law_ref_from_ya_kya_filename("N4495-2017-Something.pdf") is None
