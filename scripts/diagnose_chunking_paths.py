"""Dry-run: for every PDF in data/raw_pdfs/public, report which chunking
path it would take under the new fallback heuristic.

No Qdrant writes, no Cohere calls — just parses each PDF, runs the same
heuristic the chunker uses, and prints a per-file table.
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except AttributeError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.chunker import (
    _FALLBACK_HEURISTIC_MIN_TOKENS,
    _count_tokens,
    _decide_chunking_path,
    chunk_pages,
)
from src.ingestion.metadata_extractor import extract_metadata
from src.ingestion.pdf_parser import parse_pdf
from src.ingestion.structure_detector import find_articles
from src.ingestion.text_cleaner import clean_legal_text

BASE = Path("data/raw_pdfs/public")


def main() -> None:
    pdfs = sorted(BASE.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {BASE}")
        sys.exit(1)

    print(f"Chunking-path diagnostic over {len(pdfs)} PDFs in {BASE}")
    print(f"  Fallback heuristic min tokens: {_FALLBACK_HEURISTIC_MIN_TOKENS}\n")

    header = (
        f"  {'FILE':<48} {'TOKENS':>7} {'ARTS':>5} {'PRE%':>5} "
        f"{'PATH':<10} {'CHUNKS':>7}  REASON"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    summary = {"article-based": 0, "sliding-window": 0}

    for pdf in pdfs:
        try:
            pages = parse_pdf(pdf)
        except Exception as exc:
            print(f"  {pdf.name:<48}  PARSE ERROR: {exc}")
            continue
        if not pages:
            print(f"  {pdf.name:<48}  EMPTY")
            continue

        # Mirror the pipeline: clean each page, then run chunker
        cleaned_pages = [
            page.model_copy(update={"text": clean_legal_text(page.text, source_hint=pdf.name)})
            for page in pages
        ]

        full_text = "\n".join(p.text for p in cleaned_pages)
        articles = find_articles(full_text)
        total_tokens = _count_tokens(full_text)
        total_chars = len(full_text)
        first_pos = articles[0][0] if articles else 0
        preamble_ratio = first_pos / total_chars if total_chars else 0.0

        use_fb, reason = _decide_chunking_path(full_text, articles, total_tokens)
        path = "fallback" if use_fb else "article"

        # Actually chunk it so we can report the count
        doc = extract_metadata(cleaned_pages, source_file=pdf.name, scope="public")
        chunks = chunk_pages(cleaned_pages, doc)

        summary["sliding-window" if use_fb else "article-based"] += 1

        print(
            f"  {pdf.name[:48]:<48} {total_tokens:>7} {len(articles):>5} "
            f"{preamble_ratio:>4.0%}  {path:<10} {len(chunks):>7}  {reason}"
        )

    print()
    print(f"Summary: {summary['article-based']} article-based, "
          f"{summary['sliding-window']} sliding-window")


if __name__ == "__main__":
    main()
