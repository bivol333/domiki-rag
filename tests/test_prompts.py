"""Snapshot tests for the system prompt and user-turn template."""
import hashlib

from src.generation.prompts import (
    INVALID_CITATION_PLACEHOLDER,
    REFUSAL_PHRASE,
    SYSTEM_PROMPT,
    build_user_message,
)
from src.retrieval.hybrid_search import Hit
from src.retrieval.reranker import RankedHit


def _make_hit(article: str, text: str, page: int = 10) -> RankedHit:
    h = Hit(
        point_id=1,
        score=0.5,
        chunk_id="abc",
        source_file="N_4495.pdf",
        law_number="Ν. 4495/2017",
        fek_ref="ΦΕΚ Α' 167/2017",
        article=article,
        paragraph=None,
        page_start=page,
        page_end=page + 1,
        scope="public",
        source_type="law",
        text=text,
    )
    return RankedHit(hit=h, rerank_score=0.9, fused_score=0.7, rerank_rank=1)


class TestSystemPrompt:
    def test_prompt_is_greek(self):
        assert "Είσαι εξειδικευμένος βοηθός" in SYSTEM_PROMPT

    def test_prompt_contains_critical_rules(self):
        # Citation rule
        assert "[Source: chunk_id_X]" in SYSTEM_PROMPT
        # Refusal rule
        assert REFUSAL_PHRASE in SYSTEM_PROMPT
        # Disclaimer
        assert "ΣΗΜΕΙΩΣΗ:" in SYSTEM_PROMPT
        assert "δεν αποτελεί νομική συμβουλή" in SYSTEM_PROMPT
        # Language rule
        assert "Πάντα ελληνικά" in SYSTEM_PROMPT

    def test_prompt_forbids_emoji(self):
        assert "Δεν χρησιμοποιείς emoji" in SYSTEM_PROMPT

    def test_prompt_snapshot_hash(self):
        """If this fails, the locked system prompt was changed. Confirm intent then update hash."""
        digest = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
        # Snapshot — update only when the prompt is intentionally edited.
        expected = "a300e77eb68e7791bfcbb1f8efe2d3d998eef5cfc709cbceed8433e6a548d6f5"
        assert digest == expected, (
            f"SYSTEM_PROMPT changed!\n  expected: {expected}\n  got:      {digest}"
        )


class TestUserMessage:
    def test_renders_query_and_chunks(self):
        hits = [
            _make_hit("Άρθρο 99", "Δικαιολογητικά υπαγωγής αυθαιρέτων.", page=18),
            _make_hit("Άρθρο 100", "Πρόστιμο αυθαίρετης κατασκευής.", page=23),
        ]
        msg = build_user_message("Ποια η διαδικασία;", hits)
        assert "Ποια η διαδικασία;" in msg
        assert "=== chunk_1 ===" in msg
        assert "=== chunk_2 ===" in msg
        assert "Άρθρο 99" in msg
        assert "Άρθρο 100" in msg
        assert "Δικαιολογητικά υπαγωγής" in msg

    def test_empty_hits_still_renders(self):
        msg = build_user_message("test", [])
        assert "test" in msg
        assert "Διαθέσιμα αποσπάσματα" in msg

    def test_constants_exposed(self):
        assert REFUSAL_PHRASE == "Δεν βρίσκω επαρκή πληροφορία"
        assert INVALID_CITATION_PLACEHOLDER == "[αναφορά μη διαθέσιμη]"
