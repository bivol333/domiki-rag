"""Regex-based detection of legal structure elements in Greek legislative text."""
import re
import unicodedata

# Article: must start at beginning of a line (after optional whitespace)
ARTICLE_RE = re.compile(r"^\s*Άρθρο\s+(\d+[α-ωΑ-Ω]?)\b", re.MULTILINE)

# Paragraph: several forms used in Greek law
PARAGRAPH_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(\d+)\.\s"  # "1. Text..."
    r"|παρ\.?\s*(\d+)"  # "παρ. 4", "παρ 4"
    r"|παράγραφος\s+(\d+)"  # "παράγραφος 4"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# ΦΕΚ reference — many spacing variants
FEK_RE = re.compile(
    r"Φ\.?\s*Ε\.?\s*Κ\.?\s+"
    r"(?:τε[υύ]χο[υς]?\s+)?"
    r"([ΑΒΓΔ])'?\s*"
    r"(\d+)\s*/\s*"
    r"(\d{2,4})",
    re.IGNORECASE,
)

# Law number — Greek forms; group(1)=prefix, group(2)=number, group(3)=year
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
    """Return (start_pos, article_label) for each article heading found."""
    text = _nfc(text)
    results = []
    for m in ARTICLE_RE.finditer(text):
        label = f"Άρθρο {m.group(1)}"
        results.append((m.start(), label))
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
