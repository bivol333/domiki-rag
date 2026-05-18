"""Orchestrates parser → metadata → chunker for a single PDF file."""
import logging
from pathlib import Path

from src.ingestion.chunker import chunk_pages
from src.ingestion.metadata_extractor import extract_metadata
from src.ingestion.models import Chunk, Scope
from src.ingestion.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


def ingest_file(path: Path, scope: Scope) -> list[Chunk]:
    """Parse a PDF and return its chunks with metadata."""
    logger.info("Ingesting %s (scope=%s)", path.name, scope)

    pages = parse_pdf(path)
    if not pages:
        logger.warning("No pages extracted from %s — skipping", path.name)
        return []

    doc = extract_metadata(pages, source_file=path.name, scope=scope)
    chunks = chunk_pages(pages, doc)

    logger.info(
        "Produced %d chunks from %s (%d pages)",
        len(chunks),
        path.name,
        len(pages),
    )
    return chunks
