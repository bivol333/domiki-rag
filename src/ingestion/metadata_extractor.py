"""Regex-based metadata extraction from the first pages of a Greek legal PDF."""
import logging
import re
import unicodedata
from datetime import date

from src.ingestion.models import DocumentMetadata, Scope, SourceType
from src.ingestion.pdf_parser import PageContent
from src.ingestion.structure_detector import count_law_refs, extract_fek_refs

logger = logging.getLogger(__name__)

_THEMA_RE = re.compile(
    r"(?:Θέμα|ΘΕΜΑ)\s*[:\-]\s*(.+?)(?=\n\n|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_GREEK_MONTHS = {
    "ιανουαρίου": 1, "φεβρουαρίου": 2, "μαρτίου": 3,
    "απριλίου": 4, "μαΐου": 5, "ιουνίου": 6,
    "ιουλίου": 7, "αυγούστου": 8, "σεπτεμβρίου": 9,
    "οκτωβρίου": 10, "νοεμβρίου": 11, "δεκεμβρίου": 12,
}

_DATE_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(_GREEK_MONTHS.keys()) + r")\s+(\d{4})",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})[/-](\d{2})[/-](\d{2})\b")
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

_ISSUING_BODY_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ΥΠΟΥΡΓΕΙ(?:Ο|Ω)\s+ΠΕΡΙΒΑΛΛΟΝΤ", re.IGNORECASE), "ΥΠΕΝ"),
    (re.compile(r"ΣΥΜΒΟΥΛΙ(?:Ο|Ω)\s+ΤΗΣ\s+ΕΠΙΚΡΑΤΕΙΑΣ", re.IGNORECASE), "ΣτΕ"),
    (re.compile(r"ΣτΕ\b"), "ΣτΕ"),
    (re.compile(r"ΥΠΟΥΡΓΕΙ(?:Ο|Ω)\s+ΥΠΟΔΟΜ", re.IGNORECASE), "ΥΠΥΜΕ"),
    (re.compile(r"ΤΕΧΝΙΚ(?:Ο|Η)\s+ΕΠΙΜΕΛΗΤΗΡΙ", re.IGNORECASE), "ΤΕΕ"),
]

# ── Source type detection ─────────────────────────────────────────────────────
# Filename-based rules have highest priority (reliable, set by a human).
# Content-based rules apply only when the filename gives no clear signal.
# Presidential decree is checked BEFORE court_decision to prevent ΣτΕ cross-
# references in the body from misclassifying PD documents.

_FILENAME_TYPE_RULES: list[tuple[re.Pattern, SourceType]] = [
    (re.compile(r"^FEK[-_]|^ΦΕΚ[-_]", re.IGNORECASE), "fek"),
    (re.compile(r"^(?:ΠΔ|PD)[-_]", re.IGNORECASE), "presidential_decree"),
    (re.compile(r"^(?:Ν|N)[-_]?\d|^law[-_]", re.IGNORECASE), "law"),
    (re.compile(r"egkykl|egkyf", re.IGNORECASE), "circular"),
]

_CONTENT_TYPE_RULES: list[tuple[re.Pattern, SourceType]] = [
    (re.compile(r"ΠΡΟΕΔΡΙΚ[ΟΗ]\s+ΔΙΑΤΑΓΜ|Π\.Δ\.\s*\d", re.IGNORECASE), "presidential_decree"),
    (re.compile(r"εγκύκλι", re.IGNORECASE), "circular"),
    (re.compile(r"ΣτΕ\b|STE\b|ΣΥΜΒΟΥΛΙ[ΟΩ]\s+ΤΗΣ\s+ΕΠΙΚΡΑΤΕΙΑΣ", re.IGNORECASE), "court_decision"),
    (re.compile(r"νόμος\b", re.IGNORECASE), "law"),
    (re.compile(r"υπουργ|minister", re.IGNORECASE), "ministerial_decision"),
    (re.compile(r"τεχνικ.*(οδηγ|κανον)|ΤΟΤΕΕ|ΚΕΝΑΚ", re.IGNORECASE), "technical_spec"),
]

# ── Filename law-number extraction ────────────────────────────────────────────
# Parses common naming conventions used for Greek legal documents.
# Examples:
#   PD-41-2018-Pyroprostasia.pdf  → Π.Δ. 41/2018
#   N4178-2013-Old-Authaireta.pdf → Ν. 4178/2013
#   n44952017-demo.pdf            → Ν. 4495/2017
#   N_4495_2017.pdf               → Ν. 4495/2017

_FILENAME_PD_RE = re.compile(
    r"(?:^|[-_.])"           # start of name or separator
    r"(?:PD|ΠΔ)"             # presidential decree prefix
    r"[-_]?"                 # optional separator before number
    r"(\d{1,5})"             # decree number
    r"[-_]"                  # mandatory separator before year
    r"(\d{4})",              # 4-digit year
    re.IGNORECASE,
)

_FILENAME_N_RE = re.compile(
    r"(?:^|[-_.])"           # start or separator
    r"(?:N|Ν)"               # law (nomos) prefix
    r"[-_]?"                 # optional separator
    r"(\d{2,5})"             # law number (2–5 digits)
    r"[-_]?"                 # optional separator
    r"((?:19|20)\d{2})"      # year (19xx or 20xx)
    r"(?:[-_.]|$)",          # followed by separator or end of string
    re.IGNORECASE,
)


def _law_ref_from_filename(filename: str) -> str | None:
    """Try to extract the document's own law/decree reference from its filename.

    This is more reliable than body-text frequency analysis because filenames
    are set intentionally (e.g. PD-41-2018-... → Π.Δ. 41/2018).
    Returns None when the filename follows no recognised pattern.
    """
    m = _FILENAME_PD_RE.search(filename)
    if m:
        return f"Π.Δ. {m.group(1)}/{m.group(2)}"
    m = _FILENAME_N_RE.search(filename)
    if m:
        return f"Ν. {m.group(1)}/{m.group(2)}"
    return None


def _infer_source_type(filename: str, head_text: str) -> SourceType:
    """Infer document type from filename (priority) then content."""
    # Filename rules fire first — they are set by a human and are unambiguous
    for pattern, stype in _FILENAME_TYPE_RULES:
        if pattern.search(filename):
            return stype
    # Content rules apply when filename gives no signal
    for pattern, stype in _CONTENT_TYPE_RULES:
        if pattern.search(head_text[:500]):
            return stype
    return "other"


def _extract_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _GREEK_MONTHS.get(m.group(2).lower())
        year = int(m.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    m = _ISO_DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = _SLASH_DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def _extract_title(text: str) -> str | None:
    # Explicit "Θέμα:" subject line is the best source
    m = _THEMA_RE.search(text[:3000])
    if m:
        subject = " ".join(m.group(1).split())
        if len(subject) > 20:
            return subject

    # First non-numeric line longer than 20 chars (skips short labels like "ΕΓΚΥΚΛΙΟΣ 2")
    for ln in (line.strip() for line in text.splitlines() if line.strip()):
        if 20 < len(ln) < 200 and not re.match(r"^\d", ln):
            return ln

    return None


def _primary_law_ref(pages: list[PageContent]) -> str | None:
    """Return canonical law ref with highest frequency across the full document.

    Used as fallback when filename-based extraction is not available.
    """
    full_text = "\n".join(unicodedata.normalize("NFC", p.text) for p in pages)
    head_500 = full_text[:500]

    counts = count_law_refs(full_text)
    if not counts:
        return None

    def score(item: tuple[str, int]) -> tuple[int, int]:
        canonical, cnt = item
        in_head = 1 if canonical in head_500 else 0
        return (cnt, in_head)

    return max(counts.items(), key=score)[0]


def _extract_issuing_body(text: str) -> str | None:
    for pattern, body in _ISSUING_BODY_MAP:
        if pattern.search(text):
            return body
    return None


def extract_metadata(
    pages: list[PageContent],
    source_file: str,
    scope: Scope,
) -> DocumentMetadata:
    head_pages = pages[:3]
    head_text = "\n".join(unicodedata.normalize("NFC", p.text) for p in head_pages)

    # Law number: filename wins (prevents body cross-references from contaminating identity)
    law_number = _law_ref_from_filename(source_file)
    if law_number is None:
        law_number = _primary_law_ref(pages)

    fek_refs = extract_fek_refs(head_text)
    fek_ref = fek_refs[0] if fek_refs else None
    issue_date = _extract_date(head_text)
    title = _extract_title(head_text)
    issuing_body = _extract_issuing_body(head_text)
    source_type = _infer_source_type(source_file, head_text)

    logger.info(
        "Metadata for %s: type=%s law=%s fek=%s date=%s body=%s",
        source_file,
        source_type,
        law_number,
        fek_ref,
        issue_date,
        issuing_body,
    )

    return DocumentMetadata(
        source_file=source_file,
        source_type=source_type,
        scope=scope,
        title=title,
        law_number=law_number,
        fek_ref=fek_ref,
        issue_date=issue_date,
        issuing_body=issuing_body,
        total_pages=len(pages),
    )
