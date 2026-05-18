"""Shared Greek text tokenizer for BM25 sparse vectors.

Used by both the indexer (at index time) and the retriever (at query time).
The token→index mapping MUST be byte-identical in both paths — do not copy
or reimplement these functions; always import from here.
"""
import hashlib
import re
import unicodedata
from collections import Counter

_VOCABULARY_SIZE = 1 << 20  # 1M slots

# Word characters only, no digits — same regex as indexer
_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def tokenize_greek(text: str) -> list[str]:
    """Tokenize Greek (and Latin) text for BM25.

    - NFC unicode normalization
    - casefold (handles Greek sigma correctly, unlike lower())
    - keeps only word characters (no digits, no punctuation)
    - minimum token length: 2 characters
    """
    text = unicodedata.normalize("NFC", text)
    return [t for t in _TOKEN_RE.findall(text.casefold()) if len(t) > 1]


def token_to_index(token: str) -> int:
    """Deterministic token→int via hashlib.md5 (1M-slot vocabulary).

    MUST NOT use hash() — it is randomized per process via PYTHONHASHSEED,
    which would make sparse vectors non-reproducible across index and query runs.
    """
    digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).digest()
    return int.from_bytes(digest[:3], "little") % _VOCABULARY_SIZE


def text_to_sparse(text: str) -> dict[int, float]:
    """TF-only sparse vector suitable for query-time BM25 retrieval.

    Returns {token_index: term_frequency} compatible with Qdrant SparseVector.
    At query time we use raw TF rather than BM25 IDF (IDF is in the index).
    """
    tokens = tokenize_greek(text)
    tf: Counter[str] = Counter(tokens)
    vec: dict[int, float] = {}
    for token, freq in tf.items():
        idx = token_to_index(token)
        vec[idx] = vec.get(idx, 0.0) + float(freq)
    return vec
