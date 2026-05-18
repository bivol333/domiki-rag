"""CRITICAL: proves byte-identical tokenization between indexer and shared tokenizer.

If this test fails, hybrid retrieval silently returns wrong results because
indexer and retriever would map tokens to different sparse vector slots.
"""
import hashlib
import re
import unicodedata

import pytest

from src.common.tokenizer import text_to_sparse, token_to_index, tokenize_greek

# --- replicate the indexer's private functions verbatim for comparison ---

_INDEXER_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _indexer_tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    return [t for t in _INDEXER_TOKEN_RE.findall(text.casefold()) if len(t) > 1]


def _indexer_token_index(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).digest()
    return int.from_bytes(digest[:3], "little") % (1 << 20)


# --- Greek sample inputs ---

SAMPLES = [
    "Άρθρο 99 - Δικαιολογητικά υπαγωγής αυθαιρέτων κατασκευών",
    "πρόστιμο αυθαίρετης κατασκευής σε παραδοσιακό οικισμό",
    "Ν. 4495/2017 ΦΕΚ Α' 167 αυθαίρετα σε δάσος",
    "ΥΠΟΥΡΓΕΙΟ ΠΕΡΙΒΑΛΛΟΝΤΟΣ ΚΑΙ ΕΝΕΡΓΕΙΑΣ εγκύκλιος εφαρμογής",
    "διαδικασία υπαγωγής τακτοποίηση αυθαιρέτων παράνομων κτισμάτων",
    "Άρθρο 116 αυθαίρετα εντός παραδοσιακών οικισμών και ιστορικών τόπων",
    "Σύμβουλο της Επικρατείας απόφαση 1234/2020 κτίριο",
]


class TestTokenizeParity:
    @pytest.mark.parametrize("text", SAMPLES)
    def test_tokenize_identical(self, text: str):
        indexer_tokens = _indexer_tokenize(text)
        shared_tokens = tokenize_greek(text)
        assert shared_tokens == indexer_tokens, (
            f"Tokenization mismatch for: {text!r}\n"
            f"  indexer: {indexer_tokens}\n"
            f"  shared:  {shared_tokens}"
        )

    @pytest.mark.parametrize("text", SAMPLES)
    def test_token_indices_identical(self, text: str):
        indexer_tokens = _indexer_tokenize(text)
        for tok in indexer_tokens:
            idx_indexer = _indexer_token_index(tok)
            idx_shared = token_to_index(tok)
            assert idx_shared == idx_indexer, (
                f"Index mismatch for token {tok!r}: "
                f"indexer={idx_indexer}, shared={idx_shared}"
            )

    @pytest.mark.parametrize("text", SAMPLES)
    def test_sparse_vector_keys_match(self, text: str):
        """Sparse vector slot indices must match between indexer path and shared path."""
        indexer_tokens = _indexer_tokenize(text)
        indexer_indices = {_indexer_token_index(t) for t in indexer_tokens}

        shared_vec = text_to_sparse(text)
        shared_indices = set(shared_vec.keys())

        assert shared_indices == indexer_indices, (
            f"Sparse index key sets differ for: {text!r}\n"
            f"  only in indexer: {indexer_indices - shared_indices}\n"
            f"  only in shared:  {shared_indices - indexer_indices}"
        )


class TestTokenizerExactOutputs:
    """Lock down exact outputs to catch regressions."""

    def test_greek_article_tokens(self):
        tokens = tokenize_greek("Άρθρο 99 κατασκευή")
        assert tokens == ["άρθρο", "κατασκευή"]

    def test_casefold_not_lower(self):
        # casefold converts Σ→σ in non-final position and handles final sigma ς
        tokens = tokenize_greek("ΑΥΘΑΙΡΕΤΟΣ ΚΤΙΣΜΑ")
        assert tokens == ["αυθαιρετοσ", "κτισμα"]

    def test_min_length_filter(self):
        tokens = tokenize_greek("α αν και ή να")
        # "α" (1 char) and "η" (1 char) filtered; "αν", "και", "να" kept
        assert "α" not in tokens
        assert "αν" in tokens
        assert "και" in tokens

    def test_numbers_stripped(self):
        tokens = tokenize_greek("Άρθρο 4495 κτίριο")
        assert "4495" not in tokens
        assert "άρθρο" in tokens
        assert "κτίριο" in tokens

    def test_nfc_normalization(self):
        # NFD ά (two code points) should equal NFC ά (one code point) after normalization
        nfd = unicodedata.normalize("NFD", "αυθαίρετο")
        nfc = unicodedata.normalize("NFC", "αυθαίρετο")
        assert tokenize_greek(nfd) == tokenize_greek(nfc)

    def test_token_index_deterministic(self):
        # Same token must always produce the same index
        idx1 = token_to_index("αυθαίρετο")
        idx2 = token_to_index("αυθαίρετο")
        assert idx1 == idx2

    def test_token_index_in_range(self):
        for text in SAMPLES:
            for tok in tokenize_greek(text):
                idx = token_to_index(tok)
                assert 0 <= idx < (1 << 20), f"Index {idx} out of range for token {tok!r}"

    def test_text_to_sparse_returns_positive_values(self):
        vec = text_to_sparse("αυθαίρετο κτίριο αυθαίρετο")
        assert all(v > 0 for v in vec.values())
        # "αυθαίρετο" appears twice, should have higher weight
        idx_auth = token_to_index("αυθαίρετο")
        idx_ktir = token_to_index("κτίριο")
        assert vec[idx_auth] > vec[idx_ktir]

    def test_text_to_sparse_empty(self):
        vec = text_to_sparse("")
        assert vec == {}

    def test_text_to_sparse_only_numbers(self):
        vec = text_to_sparse("123 456 789")
        assert vec == {}
