"""PDF text extraction using PyMuPDF (primary) with pdfplumber fallback."""
import logging
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SUSPICION_MIN_CHARS = 30
_NON_GREEK_LATIN_RE = re.compile(r"[^Ͱ-Ͽἀ-῿ -~a-zA-Z0-9\s]")


class PageContent(BaseModel):
    page_number: int
    text: str
    has_tables: bool


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_suspicious(text: str) -> bool:
    if len(text.strip()) < _SUSPICION_MIN_CHARS:
        return True
    non_standard = len(_NON_GREEK_LATIN_RE.findall(text))
    return non_standard > len(text) * 0.3


def _extract_with_pdfplumber(path: Path, page_num: int) -> tuple[str, bool]:
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            page = pdf.pages[page_num]
            text = page.extract_text() or ""
            has_tables = bool(page.extract_tables())
            return _normalize(text), has_tables
    except Exception as exc:
        logger.warning("pdfplumber fallback failed for page %d of %s: %s", page_num, path.name, exc)
        return "", False


def parse_pdf(path: Path) -> list[PageContent]:
    """Extract text from each page of a PDF, NFC-normalized."""
    pages: list[PageContent] = []

    with fitz.open(str(path)) as doc:
        for page_index in range(len(doc)):
            page = doc[page_index]
            text = page.get_text("text")
            text = _normalize(text)
            has_tables = False

            if _is_suspicious(text):
                logger.warning(
                    "Suspicious text on page %d of %s — falling back to pdfplumber",
                    page_index + 1,
                    path.name,
                )
                fb_text, has_tables = _extract_with_pdfplumber(path, page_index)
                if fb_text:
                    text = fb_text

            if not text.strip():
                logger.warning(
                    "No extractable text on page %d of %s — may be scanned",
                    page_index + 1,
                    path.name,
                )

            pages.append(
                PageContent(
                    page_number=page_index + 1,
                    text=text,
                    has_tables=has_tables,
                )
            )

    logger.info("Parsed %d pages from %s", len(pages), path.name)
    return pages
