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

# ── Sliding-window fallback heuristic ─────────────────────────────────────────
# When article detection finds structure but the structure leaves a large
# preamble outside any article (e.g. PD-24-1985-Ektos-Sxediou has a 12-page
# preamble before its single Άρθρο 1), article-based chunking would silently
# discard the preamble.  These thresholds decide when to fall back to whole-
# document sliding-window chunking instead.
#
# The guard below keeps the heuristic from firing on small documents — for
# those, "preamble" is meaningless and a single detected article that covers
# the whole content should not be second-guessed.  Set well above the largest
# existing test fixture (~2900 tokens) and well below PD-24 (~15000 tokens),
# which is the smallest real-world document that needs the fallback.
_FALLBACK_HEURISTIC_MIN_TOKENS = 4000
_FALLBACK_MIN_ARTICLES = 3
_FALLBACK_PREAMBLE_RATIO_LOOSE = 0.30   # first article past 30% → fallback
_FALLBACK_PREAMBLE_RATIO_STRICT = 0.40  # more than 40% would be dropped → fallback

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


def _sliding_window_whole_doc(
    pages: list[PageContent], full_text: str, doc: DocumentMetadata
) -> list[Chunk]:
    """Chunk the ENTIRE document (including any preamble) with sentence sliding window.

    Used when article-based chunking would discard significant preamble content,
    or when no article structure is detected at all.
    """
    if not pages:
        return []

    chunks: list[Chunk] = []
    total_tokens = _count_tokens(full_text)
    page_s = pages[0].page_number
    page_e = pages[-1].page_number

    if total_tokens <= MAX_TOKENS:
        if total_tokens >= MIN_TOKENS:
            chunks.append(_make_chunk(doc, full_text, page_s, page_e, None, None))
        return chunks

    chunks.extend(_sentence_split_with_overlap(full_text, doc, page_s, page_e, None, None))
    return chunks


def _chunk_by_articles(
    pages: list[PageContent],
    full_text: str,
    articles: list[tuple[int, str]],
    doc: DocumentMetadata,
) -> list[Chunk]:
    """Article-based chunking: split at detected Άρθρο boundaries.

    NOTE: text BEFORE the first detected article (`full_text[:articles[0][0]]`)
    is discarded by this path.  Caller must decide whether that's acceptable
    via the preamble-ratio heuristic in `chunk_pages`.
    """
    # Build a position-to-page lookup
    page_breaks: list[int] = []
    offset = 0
    for p in pages:
        page_breaks.append(offset)
        offset += len(p.text) + 1  # +1 for the joining newline

    def _page_for_pos(pos: int) -> int:
        lo, hi = 0, len(page_breaks) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if page_breaks[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return pages[lo].page_number

    chunks: list[Chunk] = []
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
            # Small article → one chunk (or merge candidate; include either way)
            chunks.append(_make_chunk(doc, art_text, page_s, page_e, art_label, None))
        else:
            chunks.extend(_split_article(art_text, art_label, doc, page_s, page_e))

    return chunks


def _decide_chunking_path(
    full_text: str,
    articles: list[tuple[int, str]],
    total_tokens: int,
) -> tuple[bool, str]:
    """Return (use_sliding_window, reason).

    Falls back to whole-document sliding window when ANY of:
      • No articles detected at all
      • Document is substantial (>= _FALLBACK_HEURISTIC_MIN_TOKENS) AND:
        - fewer than 3 articles, OR
        - first article past 30% of the document, OR
        - more than 40% of the document would be dropped as preamble
        (The 40% check is strictly redundant with the 30% check under OR
        semantics, but kept explicit per the spec.)
    """
    if not articles:
        return True, "no articles detected"

    if total_tokens < _FALLBACK_HEURISTIC_MIN_TOKENS:
        # Tiny document — heuristic doesn't apply; preamble is meaningless here
        return False, ""

    total_chars = len(full_text)
    first_article_pos = articles[0][0]
    preamble_ratio = first_article_pos / total_chars if total_chars else 0.0

    if len(articles) < _FALLBACK_MIN_ARTICLES:
        return True, f"few articles ({len(articles)} < {_FALLBACK_MIN_ARTICLES})"
    if preamble_ratio > _FALLBACK_PREAMBLE_RATIO_LOOSE:
        return True, f"first article at {preamble_ratio:.0%} of doc (> 30%)"
    if preamble_ratio > _FALLBACK_PREAMBLE_RATIO_STRICT:
        return True, f"preamble {preamble_ratio:.0%} > 40%"

    return False, ""


def chunk_pages(pages: list[PageContent], doc: DocumentMetadata) -> list[Chunk]:
    """Convert parsed pages into Chunks respecting legal structure.

    Routing:
      • Article-based: when the document has substantive article structure that
        spans most of its content (typical well-formed laws).
      • Sliding-window fallback: when no articles are detected, or when article-
        based chunking would discard a significant preamble (e.g. PD-24-1985
        with 12 pages of preamble before its single detected article).
    """
    full_text = "\n".join(p.text for p in pages)
    articles = find_articles(full_text)
    total_tokens = _count_tokens(full_text)

    use_fallback, reason = _decide_chunking_path(full_text, articles, total_tokens)

    if use_fallback:
        logger.info(
            "[chunker] %s: sliding-window fallback (%s; %d articles, %d tokens)",
            doc.source_file, reason, len(articles), total_tokens,
        )
        return _sliding_window_whole_doc(pages, full_text, doc)

    logger.info(
        "[chunker] %s: article-based (%d articles, %d tokens)",
        doc.source_file, len(articles), total_tokens,
    )
    return _chunk_by_articles(pages, full_text, articles, doc)
