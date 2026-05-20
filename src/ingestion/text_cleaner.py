"""Conservative text cleaning for Greek legal PDFs.

Removes webpage noise introduced by browser Print to PDF from e-nomothesia.gr:
- Private-use Unicode glyphs (U+E000-U+F8FF, icon fonts)
- Non-breaking spaces (U+00A0)
- Known webpage chrome lines (navigation, subscription prompts, cookie banners)
- Standalone URL lines (page footers like https://www.e-nomothesia.gr/...)

All cleaning is logged per-category so it can be audited.
Conservative rule: when unsure, keep the line. Legal content must never be stripped.
"""
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Private-use area (U+E000-U+F8FF): icon fonts from webpage renderers.
# Character range built at runtime to avoid encoding issues with Unicode escapes.
_PUA_RE = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]+")

# A line whose ENTIRE content is a URL -- these are page footers injected by
# print-to-PDF. Lines that merely REFERENCE a URL within legal prose are kept.
_URL_LINE_RE = re.compile(r"^\s*https?://\S+\s*$", re.MULTILINE)


def _normalize_for_compare(text: str) -> str:
    """Casefold + strip diacritics for accent/case-insensitive comparison.

    Greek uppercase text often loses tonos (e.g. SYNDESEE vs Syndesee).
    This function normalizes both forms to the same representation so chrome
    detection is robust to casing and accent variation.
    """
    cf = text.casefold()
    nfd = unicodedata.normalize("NFD", cf)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# Exact-match chrome lines (safe to strip ONLY when the entire line equals this phrase).
# Short / ambiguous words must be exact-match so that legal sentences containing the
# same word are never removed.
# Stored in _normalize_for_compare() form for accent/case-insensitive matching.
_CHROME_EXACT: frozenset[str] = frozenset(
    _normalize_for_compare(s)
    for s in {
        "Σύνδεση",
        "e-nomothesia.gr",
        "Εκτύπωση επιλεγμένων",
        "Προσωπικές σημειώσεις",
        "Μελέτη νόμου",
        "Επόμενο άρθρο",
        "Προηγούμενο άρθρο",
        "Μετάβαση στα περιεχόμενα",
        "Τράπεζα Πληροφοριών",
    }
)

# Prefix-match chrome lines.  Lines STARTING WITH one of these phrases are chrome.
# Only include phrases specific enough that no legal text could start with them.
_CHROME_PREFIXES: tuple[str, ...] = tuple(
    _normalize_for_compare(s)
    for s in (
        "Συνδρομητικές Υπηρεσίες",
        "Τράπεζα Πληροφοριών e-nomothesia",
    )
)


def _is_chrome_line(line: str) -> bool:
    """Return True only when a line is definitively webpage chrome (safe to strip)."""
    normalized = _normalize_for_compare(line.strip())
    if not normalized:
        return False
    if normalized in _CHROME_EXACT:
        return True
    for prefix in _CHROME_PREFIXES:
        if normalized.startswith(prefix):
            return True
    # Cookie-consent fragments (must contain BOTH keywords on the same line)
    nline = _normalize_for_compare(line.strip())
    if "cookies" in nline and _normalize_for_compare("ρυθμίσεις") in nline:
        return True
    return False


def clean_legal_text(text: str, source_hint: str = "") -> str:
    """Remove webpage noise from legal text extracted via PyMuPDF.

    Args:
        text: Raw extracted text, possibly containing print-to-PDF artifacts.
        source_hint: Filename or identifier used in log messages.

    Returns:
        Cleaned text.  Paragraph breaks (double newlines) are preserved.
        The result is NFC-normalized.
    """
    label = source_hint or "unknown"
    original_len = len(text)

    # 1. Replace non-breaking spaces with regular spaces
    text = text.replace("\xa0", " ")

    # 2. Remove private-use Unicode glyphs (icon fonts)
    pua_matches = _PUA_RE.findall(text)
    pua_count = sum(len(m) for m in pua_matches)
    if pua_count:
        text = _PUA_RE.sub("", text)
        logger.debug("[clean] %s: removed %d PUA glyph(s)", label, pua_count)

    # 3. NFC normalization (must match tokenizer / structure detector)
    text = unicodedata.normalize("NFC", text)

    # 4. Remove standalone URL lines (e.g. page footers)
    url_lines = _URL_LINE_RE.findall(text)
    url_count = len(url_lines)
    if url_count:
        text = _URL_LINE_RE.sub("", text)
        logger.debug("[clean] %s: removed %d standalone URL line(s)", label, url_count)

    # 5. Remove known webpage chrome lines (line-by-line)
    lines = text.split("\n")
    clean_lines: list[str] = []
    chrome_count = 0
    for line in lines:
        if _is_chrome_line(line):
            chrome_count += 1
        else:
            clean_lines.append(line)
    if chrome_count:
        logger.debug("[clean] %s: removed %d chrome line(s)", label, chrome_count)
    text = "\n".join(clean_lines)

    # 6. Collapse multiple spaces / tabs (do NOT collapse newlines here)
    text = re.sub(r"[ \t]+", " ", text)

    # 7. Collapse excessive blank lines (> 2 consecutive -> 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = text.strip()

    removed = original_len - len(text)
    if removed > 0:
        logger.info(
            "[clean] %s: %d -> %d chars removed=%d (pua=%d, urls=%d, chrome=%d)",
            label,
            original_len,
            len(text),
            removed,
            pua_count,
            url_count,
            chrome_count,
        )

    return text
