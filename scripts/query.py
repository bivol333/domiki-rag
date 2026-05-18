"""CLI: query the retrieval pipeline and print top-K results."""
import argparse
import asyncio
import logging

from src.config import settings
from src.retrieval.retriever import Retriever

logging.basicConfig(level=logging.WARNING)


def _truncate(text: str | None, width: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:width] + "…" if len(text) > width else text


async def _run(args: argparse.Namespace) -> None:
    retriever = Retriever(collection=args.collection)
    results = await retriever.search(
        query=args.query,
        top_k=args.top_k,
        initial_k=args.initial_k,
        rerank=not args.no_rerank,
    )

    if not results:
        print("Δεν βρέθηκαν αποτελέσματα.")
        return

    col_widths = {"rank": 4, "rerank": 10, "fused": 10, "law": 20, "article": 12, "pages": 8}

    header = (
        f"{'Rank':>{col_widths['rank']}} "
        f"{'Rerank':>{col_widths['rerank']}} "
        f"{'Fused':>{col_widths['fused']}} "
        f"{'Νόμος':<{col_widths['law']}} "
        f"{'Άρθρο':<{col_widths['article']}} "
        f"{'Σελίδες':<{col_widths['pages']}}"
    )
    if args.show_text:
        header += "  Κείμενο"

    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in results:
        h = r.hit
        pages = f"{h.page_start}-{h.page_end}" if h.page_start and h.page_end else ""
        row = (
            f"{r.rerank_rank:>{col_widths['rank']}} "
            f"{r.rerank_score:>{col_widths['rerank']}.4f} "
            f"{r.fused_score:>{col_widths['fused']}.4f} "
            f"{_truncate(h.law_number, col_widths['law']):<{col_widths['law']}} "
            f"{_truncate(h.article, col_widths['article']):<{col_widths['article']}} "
            f"{pages:<{col_widths['pages']}}"
        )
        if args.show_text:
            row += f"  {_truncate(h.text, 80)}"
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Αναζήτηση στη βάση νομοθεσίας δόμησης"
    )
    parser.add_argument("query", help="Ερώτημα στα Ελληνικά")
    parser.add_argument("--top-k", type=int, default=5, metavar="N")
    parser.add_argument("--initial-k", type=int, default=50, metavar="N")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--collection", default=settings.public_collection)
    parser.add_argument("--show-text", action="store_true")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
