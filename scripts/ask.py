"""CLI: ask a question and get a grounded, cited Greek answer."""
import argparse
import asyncio
import logging
import socket
import sys

from src.generation.answer_generator import AnswerGenerator
from src.generation.claude_client import ClaudeClient
from src.generation.models import AnswerResponse
from src.observability.logger import QueryLogger
from src.pipeline.qa_pipeline import QAPipeline
from src.retrieval.retriever import Retriever

logging.basicConfig(level=logging.WARNING)


# Cohere embed-multilingual-v3.0: $0.10 / 1M tokens (input only)
# Claude Sonnet 4.6: $3 / 1M input tokens, $15 / 1M output tokens
def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0


def _print_streaming(
    pipeline: QAPipeline, query: str, top_k: int, session_id: str,
) -> AnswerResponse:
    tokens = asyncio.run(
        pipeline.ask_stream(query=query, session_id=session_id, top_k=top_k),
    )
    print()
    for delta in tokens:
        sys.stdout.write(delta)
        sys.stdout.flush()
    print("\n")
    return pipeline.finalize_stream()


def _print_response(response: AnswerResponse, show_text: bool = True) -> None:
    if show_text:
        print(response.answer_text)
        print()

    if response.citations:
        print("=" * 70)
        print("ΠΗΓΕΣ")
        print("=" * 70)
        for i, c in enumerate(response.citations, 1):
            print(f"  [{i}] {c.label}")
            print(f"      Αρχείο: {c.source_file}")
        print()

    if response.refused:
        print("⚠  Το σύστημα αρνήθηκε να απαντήσει (ανεπαρκείς πηγές).")
        print()
    if response.has_invalid_citations:
        print("⚠  Το μοντέλο αναφέρθηκε σε ανύπαρκτο απόσπασμα — δείτε [αναφορά μη διαθέσιμη].")
        print()

    print("-" * 70)
    print(
        f"Χρονισμοί: retrieval={response.timing.get('retrieval_ms', 0):.0f}ms "
        f"generation={response.timing.get('generation_ms', 0):.0f}ms "
        f"total={response.timing.get('total_ms', 0):.0f}ms"
    )
    in_tok = response.token_usage.get("input_tokens", 0)
    out_tok = response.token_usage.get("output_tokens", 0)
    cost = _estimate_cost_usd(in_tok, out_tok)
    print(f"Tokens: in={in_tok}, out={out_tok}  (~${cost:.4f})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Domiki RAG QA CLI")
    parser.add_argument("query", help="Ερώτηση στα Ελληνικά")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--json", action="store_true", help="Εκτύπωση AnswerResponse ως JSON")
    parser.add_argument(
        "--session-id",
        default=f"cli-{socket.gethostname()}",
        help="Session id under which to log this query (default: cli-{hostname})",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Skip persisting this query to data/logs.db",
    )
    args = parser.parse_args()

    retriever = Retriever()
    generator = AnswerGenerator(ClaudeClient())
    query_logger = None if args.no_log else QueryLogger()
    pipeline = QAPipeline(retriever, generator, query_logger=query_logger)
    session_id = None if args.no_log else args.session_id

    if args.no_stream or args.json:
        response = asyncio.run(
            pipeline.ask(query=args.query, session_id=session_id, top_k=args.top_k),
        )
    else:
        response = _print_streaming(pipeline, args.query, args.top_k, session_id)

    if args.json:
        print(response.model_dump_json(indent=2))
        return

    # if streaming, answer text already printed; show only metadata
    _print_response(response, show_text=args.no_stream)


if __name__ == "__main__":
    main()
