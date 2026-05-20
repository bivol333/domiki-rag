"""Chunks pages of legal text into Chunk objects respecting article/paragraph structure."""
import hashlib
import logging
import re

import tiktoken

from src.ingestion.models import Chunk, DocumentMetadata
from src.ingestion.pdf_parser import PageContent
from src.ingestion.structure_detector import find_articles, find_paragraphs

logger = logging.getLogger(__name__)

MAX_TOKENS = 800
MIN_TOKENS = 100
OVERLAP_TOKENS = 100

_ENC = tiktoken.get_encoding("cl100k_base")

_SENT_RE = re.compile(r"(?<=[.!?;])\s+")


def _count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def _chunk_id(source_file: str, page_start: int, page_end: int, text: str) -> str:
    # Hash the full text to guarantee uniqueness (header prefix alone causes collisions)
    raw = f"{source_file}|{page_start}|{page_end}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _make_header(doc: DocumentMetadata, article: str | None, paragraph: str | None) -> str:
    parts = []
    if doc.law_number:
        parts.append(doc.law_number)
    if doc.fek_ref:
        parts.append(doc.fek_ref)
    location = " ".join(filter(None, [article, paragraph]))
    source_part = " - ".join(parts) if parts else doc.source_file
    header = f"[ΠΗΓΗ: {source_part}"
    if location:
        header += f" | {location}"
    header += "]"
    return header


def _make_chunk(
    doc: DocumentMetadata,
    text: str,
    page_start: int,
    page_end: int,
    article: str | None,
    paragraph: str | None,
) -> Chunk:
    header = _make_header(doc, article, paragraph)
    full_text = f"{header}\n\n{text}"
    return Chunk(
        chunk_id=_chunk_id(doc.source_file, page_start, page_end, full_text),
        document=doc,
        text=full_text,
        page_start=page_start,
        page_end=page_end,
        article=article,
        paragraph=paragraph,
        char_count=len(full_text),
        token_count=_count_tokens(full_text),
    )


def _sentence_split_with_overlap(
    text: str,
    doc: DocumentMetadata,
    page_start: int,
    page_end: int,
    article: str | None,
    paragraph: str | None,
) -> list[Chunk]:
    sentences = _SENT_RE.split(text)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = _count_tokens(sent)
        if current_tokens + sent_tokens > MAX_TOKENS and current:
            chunks.append(
                _make_chunk(doc, " ".join(current), page_start, page_end, article, paragraph)
            )
            # Keep overlap
            overlap: list[str] = []
            overlap_tok = 0
            for s in reversed(current):
                t = _count_tokens(s)
                if overlap_tok + t > OVERLAP_TOKENS:
                    break
                overlap.insert(0, s)
                overlap_tok += t
            current = overlap
            current_tokens = overlap_tok

        current.append(sent)
        current_tokens += sent_tokens

    if current:
        chunks.append(_make_chunk(doc, " ".join(current), page_start, page_end, article, paragraph))

    return chunks


def _split_article(
    article_text: str,
    article_label: str,
    doc: DocumentMetadata,
    page_start: int,
    page_end: int,
) -> list[Chunk]:
    """Split an oversized article into paragraph-level or sentence-level chunks."""
    paragraphs = find_paragraphs(article_text)

    if not paragraphs:
        return _sentence_split_with_overlap(
            article_text, doc, page_start, page_end, article_label, None
        )

    # Build paragraph spans
    boundaries = [(pos, label) for pos, label in paragraphs] + [(len(article_text), None)]
    chunks: list[Chunk] = []
    merge_buffer: list[tuple[str, str]] = []
    merge_tokens = 0

    def flush_buffer() -> None:
        if not merge_buffer:
            return
        combined = " ".join(t for t, _ in merge_buffer)
        para_label = merge_buffer[0][1]
        chunks.append(
            _make_chunk(doc, combined, page_start, page_end, article_label, para_label)
        )
        merge_buffer.clear()

    for i in range(len(boundaries) - 1):
        pos, para_label = boundaries[i]
        end_pos = boundaries[i + 1][0]
        para_text = article_text[pos:end_pos].strip()
        if not para_text:
            continue
        para_tokens = _count_tokens(para_text)

        if para_tokens > MAX_TOKENS:
            flush_buffer()
            merge_tokens = 0
            chunks.extend(
                _sentence_split_with_overlap(
                    para_text, doc, page_start, page_end, article_label, para_label
                )
            )
        elif merge_tokens + para_tokens > MAX_TOKENS:
            flush_buffer()
            merge_tokens = 0
            merge_buffer.append((para_text, para_label))
            merge_tokens = para_tokens
        else:
            merge_buffer.append((para_text, para_label))
            merge_tokens += para_tokens

    flush_buffer()
    return chunks


def chunk_pages(pages: list[PageContent], doc: DocumentMetadata) -> list[Chunk]:
    """Convert parsed pages into Chunks respecting legal structure."""
    full_text = "\n".join(p.text for p in pages)
    page_breaks: list[int] = []
    offset = 0
    for p in pages:
        page_breaks.append(offset)
        offset += len(p.text) + 1  # +1 for newline

    def _page_for_pos(pos: int) -> int:
        lo, hi = 0, len(page_breaks) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if page_breaks[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return pages[lo].page_number

    articles = find_articles(full_text)
    chunks: list[Chunk] = []

    if not articles:
        # No article structure — fall back to sliding-window chunking
        logger.warning(
            "No articles detected in %s — falling back to sliding-window chunking",
            doc.source_file,
        )
        total_tokens = _count_tokens(full_text)
        if total_tokens <= MAX_TOKENS:
            if total_tokens >= MIN_TOKENS:
                chunks.append(
                    _make_chunk(
                        doc, full_text, pages[0].page_number, pages[-1].page_number, None, None
                    )
                )
        else:
            chunks.extend(
                _sentence_split_with_overlap(
                    full_text, doc, pages[0].page_number, pages[-1].page_number, None, None
                )
            )
        return chunks

    # Process each article span
    article_boundaries = [(pos, label) for pos, label in articles] + [(len(full_text), None)]

    for i in range(len(article_boundaries) - 1):
        art_pos, art_label = article_boundaries[i]
        art_end = article_boundaries[i + 1][0]
        art_text = full_text[art_pos:art_end].strip()
        if not art_text:
            continue

        page_s = _page_for_pos(art_pos)
        page_e = _page_for_pos(min(art_end - 1, len(full_text) - 1))
        art_tokens = _count_tokens(art_text)

        if art_tokens <= MAX_TOKENS:
            if art_tokens >= MIN_TOKENS:
                chunks.append(_make_chunk(doc, art_text, page_s, page_e, art_label, None))
            else:
                # Too small — merge with next if possible (just include it anyway)
                chunks.append(_make_chunk(doc, art_text, page_s, page_e, art_label, None))
        else:
            chunks.extend(_split_article(art_text, art_label, doc, page_s, page_e))

    return chunks
