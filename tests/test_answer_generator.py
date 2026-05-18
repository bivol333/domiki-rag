"""Tests for AnswerGenerator with a mocked ClaudeClient."""
from unittest.mock import MagicMock

from src.generation.answer_generator import AnswerGenerator
from src.generation.claude_client import GenerationResult, StreamingGenerationResult
from src.retrieval.hybrid_search import Hit
from src.retrieval.reranker import RankedHit


def _make_hit(article: str, text: str) -> RankedHit:
    h = Hit(
        point_id=1, score=0.5, chunk_id="cid",
        source_file="law.pdf", law_number="Ν. 4495/2017",
        fek_ref=None, article=article, paragraph=None,
        page_start=10, page_end=11, scope="public",
        source_type="law", text=text,
    )
    return RankedHit(hit=h, rerank_score=0.9, fused_score=0.7, rerank_rank=1)


class TestGenerateNonStreaming:
    def test_returns_answer_response_with_citations(self):
        client = MagicMock()
        client.generate.return_value = GenerationResult(
            text="Η διαδικασία υπαγωγής [Source: chunk_1].",
            input_tokens=300,
            output_tokens=50,
            elapsed_ms=1200.0,
        )
        gen = AnswerGenerator(client)
        hits = [_make_hit("Άρθρο 99", "δείγμα")]

        resp = gen.generate("Ποια η διαδικασία;", hits)

        assert resp.query == "Ποια η διαδικασία;"
        assert "[Source: chunk_1]" in resp.answer_text
        assert len(resp.citations) == 1
        assert resp.citations[0].article == "Άρθρο 99"
        assert resp.refused is False
        assert resp.has_invalid_citations is False
        assert resp.token_usage == {"input_tokens": 300, "output_tokens": 50}

    def test_detects_refusal(self):
        client = MagicMock()
        client.generate.return_value = GenerationResult(
            text="Δεν βρίσκω επαρκή πληροφορία στις διαθέσιμες πηγές...",
            input_tokens=300, output_tokens=30, elapsed_ms=1000.0,
        )
        gen = AnswerGenerator(client)
        resp = gen.generate("άσχετη ερώτηση", [_make_hit("Άρθρο 1", "x")])
        assert resp.refused is True
        assert resp.citations == []

    def test_invalid_citation_flagged(self):
        client = MagicMock()
        client.generate.return_value = GenerationResult(
            text="Κάτι [Source: chunk_5].",
            input_tokens=100, output_tokens=20, elapsed_ms=500.0,
        )
        gen = AnswerGenerator(client)
        resp = gen.generate("q", [_make_hit("Άρθρο 99", "x")])
        assert resp.has_invalid_citations is True
        assert "[αναφορά μη διαθέσιμη]" in resp.answer_text
        assert resp.citations == []

    def test_passes_system_prompt_and_user_message(self):
        client = MagicMock()
        client.generate.return_value = GenerationResult(
            text="ok [Source: chunk_1]", input_tokens=1, output_tokens=1, elapsed_ms=1.0,
        )
        gen = AnswerGenerator(client)
        gen.generate("X;", [_make_hit("Άρθρο 1", "Y")])

        call = client.generate.call_args
        system = call.kwargs.get("system") or call.args[0]
        user = call.kwargs.get("user") or call.args[1]
        assert "Είσαι εξειδικευμένος βοηθός" in system
        assert "X;" in user
        assert "chunk_1" in user


class TestStreaming:
    def test_stream_then_finalize(self):
        client = MagicMock()
        client.stream.return_value = iter(["Η ", "διαδικασία ", "[Source: chunk_1]."])
        client.get_last_stream_result.return_value = StreamingGenerationResult(
            text="Η διαδικασία [Source: chunk_1].",
            input_tokens=200, output_tokens=40, elapsed_ms=900.0,
        )
        gen = AnswerGenerator(client)
        hits = [_make_hit("Άρθρο 99", "x")]

        # consume the stream
        tokens = list(gen.stream("q", hits))
        assert "".join(tokens) == "Η διαδικασία [Source: chunk_1]."

        # finalize
        resp = gen.finalize("q", hits)
        assert len(resp.citations) == 1
        assert resp.refused is False
        assert resp.token_usage == {"input_tokens": 200, "output_tokens": 40}
