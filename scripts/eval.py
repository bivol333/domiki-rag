"""CLI: run evaluation suite and print report."""
import argparse
import asyncio
import datetime
import logging
import sys
from pathlib import Path

from src.evaluation.run_eval import format_report, run_eval

logging.basicConfig(level=logging.WARNING)


async def _run(args: argparse.Namespace) -> int:
    print("Εκτέλεση αξιολόγησης...", flush=True)
    report = await run_eval()

    text = format_report(report)
    print()
    print(text)

    if args.output:
        out_dir = Path("data/eval")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"report_{ts}.md"
        out_path.write_text(text, encoding="utf-8")
        print(f"\nΑναφορά αποθηκεύτηκε: {out_path}")

    return 0 if report.recall_at_5 >= 0.6 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Αξιολόγηση pipeline ανάκτησης")
    parser.add_argument(
        "--output",
        action="store_true",
        help="Αποθήκευση αναφοράς στο data/eval/",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
