"""Orchestrates parser → text_cleaner → metadata → chunker for a single PDF file."""
import logging
from pathlib import Path

from src.ingestion.chunker import chunk_pages
from src.ingestion.metadata_extractor import extract_metadata
from src.ingestion.models import Chunk, Scope
from src.ingestion.pdf_parser import parse_pdf
from src.ingestion.text_cleaner import clean_legal_text

logger = logging.getLogger(__name__)


def ingest_file(path: Path, scope: Scope) -> list[Chunk]:
    """Parse a PDF and return its chunks with metadata.

    Pipeline:
        1. parse_pdf          — PyMuPDF text extraction, per page
        2. clean_legal_text   — remove webpage noise (PUA glyphs, chrome, URLs)
        3. extract_metadata   — law number, source type, date, etc.
        4. chunk_pages        — article-based or sliding-window chunking
    """
    logger.info("Ingesting %s (scope=%s)", path.name, scope)

    try:
        pages = parse_pdf(path)
    except Exception:
        logger.exception("PDF parse failed for %s — skipping", path.name)
        return []

    if not pages:
        logger.warning("No pages extracted from %s — skipping", path.name)
        return []

    # Clean each page independently so page-number metadata is preserved
    cleaned_pages = [
        page.model_copy(update={"text": clean_legal_text(page.text, source_hint=path.name)})
        for page in pages
    ]

    try:
        doc = extract_metadata(cleaned_pages, source_file=path.name, scope=scope)
        chunks = chunk_pages(cleaned_pages, doc)
    except Exception:
        logger.exception(
            "Structure/chunking failed for %s — skipping (parse succeeded, %d pages)",
            path.name,
            len(pages),
        )
        return []

    logger.info(
        "Produced %d chunks from %s (%d pages)",
        len(chunks),
        path.name,
        len(pages),
    )
    return chunks
