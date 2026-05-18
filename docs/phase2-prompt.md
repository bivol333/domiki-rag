# Phase 2: Retrieval Pipeline

Read `CLAUDE.md` first for project context and conventions. Phase 1 is complete with all 4 metadata bugs and the critical `hash()` → `hashlib.md5` tokenizer bug fixed. The `domiki_public` collection has 172 chunks with proper metadata. Do not re-ingest unless required by a specific test.

## Goal of this phase

Given a user query in Greek (e.g. "μπορώ να χτίσω πισίνα σε εκτός σχεδίου ακίνητο;"), return the top-K most relevant chunks from `domiki_public`, with hybrid retrieval (dense + sparse), reranking, and proper citations attached. No LLM generation yet (Phase 3).

End state: I can run `uv run python scripts/query.py "ερώτηση"` and get back the top 5 chunks with their citations (law, article, page, scope) and rerank scores. Eval framework can score retrieval quality on a small test set.

## Critical tokenizer constraint

**The query-time tokenizer MUST be byte-identical to the indexing-time tokenizer.** This is the lesson from the `hash()` → `hashlib.md5` Phase 1 bug. Implement this in **one shared module** that both indexer and retriever import:

```
src/common/tokenizer.py
```

The indexer's existing token→integer mapping (`_token_index` in `src/indexing/indexer.py`) and any BM25 tokenization logic should be **moved** into this shared module. The retriever imports the same functions. Add a pytest test that proves byte-level equality between indexer-side and retriever-side tokenization on Greek sample text.

If you don't do this, hybrid retrieval returns zero or random results, silently.

## Deliverables

Create these files:

```
src/common/
└── tokenizer.py             # moved from indexer; greek text tokenize + token→int via md5

src/retrieval/
├── query_processor.py       # normalize query, detect intent hints
├── hybrid_search.py         # parallel dense+sparse Qdrant queries, score fusion
├── reranker.py              # Cohere Rerank 3 wrapper
└── retriever.py             # main interface: Retriever.search(query) -> RetrievalResult[]

src/evaluation/
├── models.py                # TestCase, RetrievalResult, EvalReport pydantic models
├── test_cases.py            # small initial eval set (10-15 hand-written cases)
└── run_eval.py              # runs queries through retriever, scores

scripts/
├── query.py                 # CLI: take query string, print top-K results + scores
└── eval.py                  # CLI: runs eval suite, prints report

tests/
├── test_tokenizer_parity.py # CRITICAL: indexer-side and retriever-side produce identical output
├── test_hybrid_search.py
├── test_reranker.py
└── test_retriever_e2e.py    # end-to-end on real Qdrant collection
```

Refactor `src/indexing/indexer.py` to import from `src/common/tokenizer.py` instead of having its own copy.

## Implementation specifications

### `src/common/tokenizer.py`

Pure functions, no class needed (or a thin class is fine):

```python
def tokenize_greek(text: str) -> list[str]:
    """Tokenize Greek text for BM25.
    
    Normalize: NFC unicode, casefold (not lower() - for proper Greek).
    Remove: punctuation, numbers (unless attached to words like '4495/2017').
    Keep: Greek-language tokens, alphanumerics.
    Min token length: 2 chars.
    """

def token_to_index(token: str) -> int:
    """Deterministic token→int via hashlib.md5. 
    Identical to indexer's _token_index. 1M-slot vocabulary."""

def text_to_sparse(text: str) -> dict[int, float]:
    """BM25-style sparse vector. token_index -> tf weight.
    Returns format compatible with Qdrant SparseVector."""
```

Add tests that lock down the exact output: feed in 3-4 fixed Greek strings, assert exact token lists and exact index values.

### `src/retrieval/query_processor.py`

Light-weight preprocessing of the user query before hitting retrieval:

```python
class ProcessedQuery(BaseModel):
    raw: str
    normalized: str  # NFC, trimmed
    detected_articles: list[str]  # if user wrote "άρθρο 23", extract
    detected_law_refs: list[str]  # if user wrote "ν.4495/2017"
    keywords: list[str]           # extracted dominant nouns (rough)
```

The detected refs become filter hints for retrieval. Don't be clever; regex match the same patterns as the structure_detector uses.

### `src/retrieval/hybrid_search.py`

Wrap Qdrant's hybrid query (dense + sparse in one request using Qdrant's native hybrid API where available, or two parallel queries + manual fusion):

```python
async def hybrid_search(
    query: str,
    collection: str = settings.public_collection,
    initial_k: int = 50,      # how many to fetch before rerank
    article_filter: list[str] | None = None,
    law_filter: list[str] | None = None,
) -> list[Hit]:
    ...
```

Score fusion: use Reciprocal Rank Fusion (RRF) with k=60 (the standard). Don't try to normalize raw cosine and BM25 scores — RRF on ranks is cleaner.

`Hit` is a pydantic model wrapping the chunk metadata + the fused score.

### `src/retrieval/reranker.py`

Wrap Cohere Rerank 3 (`rerank-multilingual-v3.0`):

```python
async def rerank(
    query: str,
    hits: list[Hit],
    top_k: int = 10,
) -> list[RankedHit]:
    ...
```

- Send the chunk text (full text including header context) to Cohere with the query
- `RankedHit` carries both the original fused_score and the rerank_score
- Retry once on transient errors, then raise

### `src/retrieval/retriever.py`

Main interface used by everything else:

```python
class Retriever:
    def __init__(self, ...):
        ...
    
    async def search(
        self, 
        query: str, 
        top_k: int = 10,
        initial_k: int = 50,
        rerank: bool = True,
    ) -> list[RankedHit]:
        # 1. process query
        # 2. hybrid_search to get initial_k
        # 3. rerank to top_k (if rerank=True)
        # 4. return RankedHit list
```

Logs each step at INFO with timings.

### `scripts/query.py`

Argparse CLI:

```
Usage: query.py "query string" [--top-k N] [--no-rerank] [--collection NAME] [--show-text]

Output: pretty-printed table of:
  rank | rerank_score | fused_score | law | article | page | (text preview if --show-text)
```

### `src/evaluation/test_cases.py`

Hand-write 10-15 test cases. Each:

```python
class TestCase(BaseModel):
    query: str
    expected_articles: list[str]      # at least one of these should appear in top-5
    expected_law: str | None          # if specific law expected
    notes: str                        # why this case is interesting
```

Examples to seed (you write the rest):
- "διαδικασία υπαγωγής αυθαιρέτου" → expects άρθρο 99 (δικαιολογητικά), 100 (πρόστιμο), or 96 (κατηγορίες)
- "πρόστιμο αυθαίρετης κατασκευής" → expects άρθρο 100, 101
- "αυθαίρετο σε παραδοσιακό οικισμό" → expects άρθρο 116
- "αυθαίρετα σε δάσος" → look for relevant article
- "Άρθρο 96" → exact article reference test (should hit the article filter)

### `src/evaluation/run_eval.py`

Run all test cases through retriever, compute:
- **Recall@5**: fraction of cases where at least one expected article appears in top 5
- **Recall@10**: same for top 10
- **MRR** (Mean Reciprocal Rank): 1/rank of first hit, averaged
- Average rerank latency
- Cases that completely failed (recall@10 = 0)

Output a markdown table and exit code 0 if Recall@5 ≥ 0.6, else 1.

### `scripts/eval.py`

Wraps `run_eval` with CLI. Outputs to console and optionally to `data/eval/report_TIMESTAMP.md`.

## Acceptance criteria

Phase 2 is done when:

- [ ] `uv run pytest tests/` passes including the new `test_tokenizer_parity.py`
- [ ] `test_tokenizer_parity.py` proves identical output between indexer code path and retriever code path on at least 5 Greek sample inputs
- [ ] `uv run ruff check src/ scripts/ tests/` clean
- [ ] `uv run python scripts/query.py "αυθαίρετα σε παραδοσιακούς οικισμούς"` returns plausible top-5 hits (article 116 should appear)
- [ ] `uv run python scripts/eval.py` runs the eval suite, prints a report, returns Recall@5 ≥ 0.6
- [ ] At least one test case in the eval set actually fails (recall@10 = 0) — this is fine for now, it tells us where to improve
- [ ] Hybrid search (dense+sparse fusion) provably better than dense-only: run `scripts/query.py --no-rerank` once with `hybrid_search` and once with a dense-only path on the same query; show the rank lists differ meaningfully on at least one test case

## Performance targets (informational, not blocking)

- Query → top 50 chunks (hybrid): < 500ms
- Rerank top 50 → top 10: < 1.5s (Cohere API call)
- Total end-to-end: < 2s typical

## Out of scope — DO NOT DO IN THIS PHASE

- LLM generation / answer synthesis (Phase 3)
- Streamlit UI (Phase 3)
- Citation formatting for end-user display (Phase 3)
- User auth, multi-user
- New ingestion features
- Modifying CLAUDE.md or pyproject.toml beyond adding Cohere rerank import if missing
- Adding test fixtures with new PDFs

## Implementation order

1. `src/common/tokenizer.py` + parity test (proves no regression in indexing)
2. Refactor `indexer.py` to use shared tokenizer
3. Re-run a small re-index test to confirm no behavior change (or skip if confident)
4. `query_processor.py` + tests
5. `hybrid_search.py` + tests against live Qdrant
6. `reranker.py` + tests (can mock Cohere for unit tests, hit live for integration)
7. `retriever.py` (composes the above)
8. `scripts/query.py` + sanity check
9. `test_cases.py` (write 10-15 cases)
10. `run_eval.py` + `scripts/eval.py`
11. Run full eval, report results

Ask clarifying questions before implementing if the spec is ambiguous. Particularly around tokenizer behavior and the Qdrant hybrid search API surface, since those can vary.
