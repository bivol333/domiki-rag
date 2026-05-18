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

_SOURCE_TYPE_RULES: list[tuple[re.Pattern, SourceType]] = [
    (re.compile(r"^FEK_|^ΦΕΚ_", re.IGNORECASE), "fek"),
    (re.compile(r"ΣτΕ|STE", re.IGNORECASE), "court_decision"),
    (re.compile(r"^ΠΔ_|^PD_|Π\.Δ\.", re.IGNORECASE), "presidential_decree"),
    (re.compile(r"εγκύκλι|egkyf", re.IGNORECASE), "circular"),
    (re.compile(r"^Ν_|^N_|νόμος|^law_", re.IGNORECASE), "law"),
    (re.compile(r"υπουργ|minister", re.IGNORECASE), "ministerial_decision"),
    (re.compile(r"τεχνικ.*(οδηγ|κανον)|ΤΟΤΕΕ|ΚΕΝΑΚ", re.IGNORECASE), "technical_spec"),
]


def _infer_source_type(filename: str, head_text: str) -> SourceType:
    for pattern, stype in _SOURCE_TYPE_RULES:
        if pattern.search(filename) or pattern.search(head_text[:500]):
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
    """Return canonical law ref with highest frequency across the full document."""
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

    law_number = _primary_law_ref(pages)  # frequency-based, full document
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
