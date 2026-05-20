"""Regex-based detection of legal structure elements in Greek legislative text."""
import re
import unicodedata

# ── Article heading patterns ──────────────────────────────────────────────────
#
# Covers all documented variants:
#   Digit-numbered:  Άρθρο 5, Άρθρο 5α, Άρθρο 5Α
#                    Άρθρον 5 (καθαρεύουσα), ΑΡΘΡΟ 5, ΑΡΘΡΟΝ 5 (uppercase)
#                    Άρθ. 5, Αρθρ. 5, Αρθ. 5 (abbreviations)
#                    With/without tonos: Αρθρο / Άρθρο
#                    Optional period/colon after number: Άρθρο 5. / Άρθρο 5:
#   Ordinal:         Άρθρο Πρώτο, Άρθρο Δεύτερο, ... Άρθρο Εικοστό
#                    ΑΡΘΡΟ ΠΡΩΤΟ (uppercase)
#
# All patterns require line-start anchoring (re.MULTILINE) to avoid matching
# mid-sentence cross-references like "σύμφωνα με το άρθρο 5".

_ART_PREFIXES = (
    r"ΆΡΘΡΟ[Ν]?"    # uppercase Greek WITH tonos
    r"|ΑΡΘΡΟ[Ν]?"   # uppercase Greek WITHOUT tonos (all-caps)
    r"|Άρθρο[ν]?"   # title-case WITH tonos
    r"|Αρθρο[ν]?"   # title-case WITHOUT tonos
    r"|ΑΡΘ\."       # uppercase abbreviation
    r"|Άρθ\."       # mixed-case abbreviation WITH tonos
    r"|Αρθρ\."      # mixed-case abbreviation (longer)
    r"|Αρθ\."       # mixed-case abbreviation (shorter)
)

# Digit-numbered articles: captures number in group(1), optional letter suffix in group(2).
# NOTE: no \s* between number and suffix — the suffix must immediately follow the digit,
# otherwise newlines are consumed and the first letter of the next line is captured.
ARTICLE_DIGIT_RE = re.compile(
    rf"^\s*(?:{_ART_PREFIXES})\s+(\d+)([Α-Ωα-ω]?)",
    re.IGNORECASE | re.MULTILINE,
)

# Word-ordinal articles: captures ordinal word in group(1)
# Uses [^\W\d]+ to match Unicode word chars that are NOT digits (avoids matching "5")
ARTICLE_ORDINAL_RE = re.compile(
    rf"^\s*(?:{_ART_PREFIXES})\s+([^\W\d]+)",
    re.IGNORECASE | re.MULTILINE,
)

# ── Greek ordinal → integer mapping ──────────────────────────────────────────
# Stems (after diacritic-stripping and casefold) keyed by unambiguous prefix.
# Order matters: longer stems before shorter prefixes that could overlap.
_GREEK_ORDINAL_STEMS: list[tuple[str, int]] = [
    ("ενδεκατ", 11),   # ενδέκατο (must come before "ενατ")
    ("δωδεκατ", 12),
    ("εικοστ", 20),
    ("δευτερ", 2),
    ("τεταρτ", 4),
    ("πεμπτ", 5),
    ("εβδομ", 7),
    ("ενατ", 9),       # ένατο
    ("δεκατ", 10),
    ("πρωτ", 1),       # πρώτο, πρώτον
    ("τριτ", 3),
    ("εκτ", 6),
    ("ογδο", 8),
]


def _strip_diacritics(text: str) -> str:
    """Remove Greek diacritics (tonos/varia/oxia) for accent-insensitive matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _ordinal_to_int(word: str) -> int | None:
    """Map a Greek ordinal word (any case, any accentuation) to its integer value."""
    normalized = _strip_diacritics(word.casefold())
    for stem, num in _GREEK_ORDINAL_STEMS:
        if normalized.startswith(stem):
            return num
    return None


# ── Paragraph detection ───────────────────────────────────────────────────────
PARAGRAPH_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(\d+)\.\s"  # "1. Text..."
    r"|παρ\.?\s*(\d+)"  # "παρ. 4", "παρ 4"
    r"|παράγραφος\s+(\d+)"  # "παράγραφος 4"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# ── ΦΕΚ reference ─────────────────────────────────────────────────────────────
FEK_RE = re.compile(
    r"Φ\.?\s*Ε\.?\s*Κ\.?\s+"
    r"(?:τε[υύ]χο[υς]?\s+)?"
    r"([ΑΒΓΔ])'?\s*"
    r"(\d+)\s*/\s*"
    r"(\d{2,4})",
    re.IGNORECASE,
)

# ── Law number — Greek forms ──────────────────────────────────────────────────
# group(1)=prefix, group(2)=number, group(3)=year
LAW_RE = re.compile(
    r"(Ν\.?(?:όμος)?|Π\.?Δ\.?|Υ\.?Α\.?)\s*"
    r"(\d+)\s*/\s*(\d{2,4})",
    re.IGNORECASE,
)


def _canonicalize_law_prefix(raw: str) -> str:
    """Normalize any matched law prefix to its canonical abbreviated form."""
    c = raw.strip().casefold()
    if c.startswith("ν"):
        return "Ν."
    if c.startswith("π"):
        return "Π.Δ."
    if c.startswith("υ"):
        return "Υ.Α."
    return "Ν."


def _expand_year(year: str) -> str:
    if len(year) == 2:
        return f"19{year}" if int(year) > 50 else f"20{year}"
    return year


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def find_articles(text: str) -> list[tuple[int, str]]:
    """Return (start_pos, article_label) for each article heading found.

    Labels are canonical:
    - Digit-numbered: "Άρθρο 5", "Άρθρο 5α"
    - Ordinal: "Άρθρο 1" (Πρώτο → 1, Δεύτερο → 2, ...)
    """
    text = _nfc(text)
    results: list[tuple[int, str]] = []
    seen: set[int] = set()

    # ① Digit-numbered articles
    for m in ARTICLE_DIGIT_RE.finditer(text):
        number = m.group(1)
        suffix = m.group(2) or ""
        label = f"Άρθρο {number}{suffix}"
        results.append((m.start(), label))
        seen.add(m.start())

    # ② Word-ordinal articles (e.g. "Άρθρο Πρώτο", "ΑΡΘΡΟ ΠΡΩΤΟ")
    for m in ARTICLE_ORDINAL_RE.finditer(text):
        pos = m.start()
        if pos in seen:
            continue
        num = _ordinal_to_int(m.group(1))
        if num is not None:
            results.append((pos, f"Άρθρο {num}"))

    results.sort(key=lambda x: x[0])
    return results


def find_paragraphs(text: str) -> list[tuple[int, str]]:
    """Return (start_pos, paragraph_label) for each paragraph marker found."""
    text = _nfc(text)
    results = []
    for m in PARAGRAPH_RE.finditer(text):
        num = m.group(1) or m.group(2) or m.group(3)
        label = f"παρ. {num}"
        results.append((m.start(), label))
    return results


def extract_law_refs(text: str) -> list[str]:
    """Return canonical, deduplicated law citations in order of first appearance."""
    text = _nfc(text)
    seen: dict[str, str] = {}  # "NUMBER/YEAR" -> canonical string
    for m in LAW_RE.finditer(text):
        number = m.group(2)
        year = _expand_year(m.group(3))
        key = f"{number}/{year}"
        if key not in seen:
            prefix = _canonicalize_law_prefix(m.group(1))
            seen[key] = f"{prefix} {number}/{year}"
    return list(seen.values())


def count_law_refs(text: str) -> "Counter[str]":  # noqa: F821
    """Count occurrences of each canonical law ref (for frequency-based selection)."""
    from collections import Counter

    text = _nfc(text)
    counts: Counter[str] = Counter()
    for m in LAW_RE.finditer(text):
        number = m.group(2)
        year = _expand_year(m.group(3))
        prefix = _canonicalize_law_prefix(m.group(1))
        counts[f"{prefix} {number}/{year}"] += 1
    return counts


def extract_fek_refs(text: str) -> list[str]:
    """Return all ΦΕΚ citations found in text."""
    text = _nfc(text)
    refs = []
    for m in FEK_RE.finditer(text):
        series = m.group(1).upper()
        issue = m.group(2)
        year = m.group(3)
        if len(year) == 2:
            year = f"19{year}" if int(year) > 50 else f"20{year}"
        refs.append(f"ΦΕΚ {series}' {issue}/{year}")
    return refs
