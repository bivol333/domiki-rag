# Phase 1: Ingestion Pipeline

Read `CLAUDE.md` first for project context and conventions. Everything in CLAUDE.md is binding.

## Goal of this phase

Build a pipeline that turns Greek PDFs of legislation, ΦΕΚ, εγκύκλιοι, and ΣτΕ decisions
into chunked, metadata-rich documents stored in Qdrant with both dense (Cohere) and sparse
(BM25) indexes, ready for hybrid retrieval in Phase 2.

End state: I can run `uv run python scripts/ingest.py --scope public` and have all PDFs in
`data/raw_pdfs/public/` indexed into the `domiki_public` Qdrant collection with full
metadata and re-runs are idempotent.

## Deliverables

Create these files (do not create others without asking):

```
src/ingestion/
├── models.py              # pydantic models: DocumentMetadata, Chunk
├── pdf_parser.py          # PyMuPDF wrapper, returns page-by-page text + structure hints
├── metadata_extractor.py  # regex-based extraction: law number, ΦΕΚ ref, date, title
├── structure_detector.py  # detects άρθρο/παράγραφος/εδάφιο boundaries in text
├── chunker.py             # produces Chunk objects respecting legal structure
└── pipeline.py            # orchestrates parser → metadata → chunker for one file

src/indexing/
├── qdrant_setup.py        # creates collections with proper config (dense + sparse vectors)
├── embedder.py            # Cohere embeddings wrapper, batches efficiently
└── indexer.py             # takes Chunk[] → upserts to Qdrant

scripts/
└── ingest.py              # CLI: --scope public|private, --path, --reindex, --dry-run

tests/
├── test_structure_detector.py  # Greek regex edge cases
├── test_chunker.py             # boundary respect, token limits, header context
└── test_metadata_extractor.py  # law numbers, ΦΕΚ refs, dates
```

## Implementation specifications

### `src/ingestion/models.py` - Data models

```python
from datetime import date
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

SourceType = Literal["law", "presidential_decree", "fek", "circular", "court_decision",
                     "ministerial_decision", "technical_spec", "other"]
Scope = Literal["public", "private"]

class DocumentMetadata(BaseModel):
    source_file: str               # filename only, no path
    source_type: SourceType
    scope: Scope
    title: str | None = None
    law_number: str | None = None  # e.g. "Ν. 4495/2017", "Π.Δ. 696/74"
    fek_ref: str | None = None     # e.g. "ΦΕΚ Α' 167/2017"
    issue_date: date | None = None
    issuing_body: str | None = None  # e.g. "ΥΠΕΝ", "ΣτΕ"
    total_pages: int

class Chunk(BaseModel):
    chunk_id: str                   # deterministic hash, allows idempotent reindex
    document: DocumentMetadata
    text: str                       # the actual chunk text (may include header context)
    page_start: int
    page_end: int
    article: str | None = None      # e.g. "Άρθρο 23"
    paragraph: str | None = None    # e.g. "παρ. 4"
    char_count: int
    token_count: int                # tiktoken count (cl100k_base is fine)
```

### `src/ingestion/pdf_parser.py`

- Use PyMuPDF (`import fitz`)
- Function: `parse_pdf(path: Path) -> list[PageContent]`
- `PageContent` is a pydantic model with: `page_number: int`, `text: str`, `has_tables: bool`
- Always normalize text with `unicodedata.normalize("NFC", text)`
- Strip excessive whitespace but PRESERVE newlines (they help structure detection)
- For pages where text extraction looks suspicious (very short text, lots of non-Greek), fall back to `pdfplumber` and log a warning
- DO NOT do OCR in this phase - just detect and warn if a page has no extractable text

### `src/ingestion/structure_detector.py`

Detect legal-text structural elements with regex. Patterns (test these thoroughly):

```python
# Article patterns - Greek (with tonos) and rare Latinized variants
ARTICLE_RE = re.compile(r'^\s*Άρθρο\s+(\d+[α-ωΑ-Ω]?)\b', re.MULTILINE)

# Paragraph patterns - several forms used in Greek law
PARAGRAPH_RE = re.compile(
    r'(?:^|\n)\s*(?:'
    r'(\d+)\.\s'              # "1. Text..."
    r'|παρ\.?\s*(\d+)'         # "παρ. 4", "παρ 4"
    r'|παράγραφος\s+(\d+)'     # "παράγραφος 4"
    r')',
    re.IGNORECASE | re.MULTILINE
)

# ΦΕΚ reference - many spacing variants
FEK_RE = re.compile(
    r'Φ\.?\s*Ε\.?\s*Κ\.?\s+'
    r"(?:τ[εε]ύχο[υς]?\s+)?"
    r"([ΑΒΓΔ])'?\s*"          # tefchos: A', B', etc.
    r'(\d+)\s*/\s*'           # issue number
    r'(\d{2,4})',             # year
    re.IGNORECASE
)

# Law number - Greek forms
LAW_RE = re.compile(
    r'(?:Ν(?:όμος)?|Π\.?Δ\.?|Υ\.?Α\.?)\s*'
    r'(\d+)\s*/\s*(\d{2,4})',
    re.IGNORECASE
)
```

Functions to implement:
- `find_articles(text: str) -> list[tuple[int, str]]` - returns (start_pos, article_label)
- `find_paragraphs(text: str) -> list[tuple[int, str]]` - same shape
- `extract_law_refs(text: str) -> list[str]` - all law citations
- `extract_fek_refs(text: str) -> list[str]` - all ΦΕΚ citations

### `src/ingestion/metadata_extractor.py`

- Function: `extract_metadata(pages: list[PageContent], source_file: str, scope: Scope) -> DocumentMetadata`
- Look in the FIRST 3 pages for: title, law/PD/UA number, ΦΕΚ ref, date
- Infer `source_type` from filename pattern + content (e.g. filename starts with "FEK_" → fek; contains "ΣτΕ" → court_decision)
- For `issuing_body`, look for common patterns: "ΥΠΟΥΡΓΕΙΟ ΠΕΡΙΒΑΛΛΟΝΤΟΣ ΚΑΙ ΕΝΕΡΓΕΙΑΣ" → "ΥΠΕΝ", "Συμβούλιο της Επικρατείας" → "ΣτΕ"
- If extraction fails, return DocumentMetadata with the field as `None`. NEVER guess.
- Log every extraction at INFO level so we can debug parsing of new doc types

### `src/ingestion/chunker.py`

Chunking strategy (in order of preference):

1. **Article-level chunks**: If an άρθρο fits in `MAX_TOKENS` (800), one άρθρο = one chunk
2. **Paragraph-level chunks**: If άρθρο too big, split by παράγραφος, keep άρθρο label in metadata. Multiple consecutive small paragraphs from same article can be merged up to `MAX_TOKENS`
3. **Sentence-level chunks**: If a single paragraph exceeds `MAX_TOKENS`, fall back to sentence-aware splitting with 100-token overlap

Configuration:
```python
MAX_TOKENS = 800      # cl100k_base tokens
MIN_TOKENS = 100      # don't make sub-100-token chunks (merge with neighbor)
OVERLAP_TOKENS = 100  # only for sentence-fallback case
```

**Header context** (important): Every chunk's `text` field should start with a synthetic header
that gives retrieval enough context. Format:

```
[ΠΗΓΗ: Ν. 4495/2017 - ΦΕΚ Α' 167/2017 | Άρθρο 23 παρ. 4]

<actual chunk content>
```

This makes each chunk self-contained for retrieval and the LLM can cite directly.

`chunk_id` is `sha256(source_file + page_start + page_end + first_50_chars_of_text)[:16]` -
deterministic and stable for idempotent reindexing.

Use `tiktoken.get_encoding("cl100k_base")` for token counting (close enough for Cohere).

### `src/indexing/qdrant_setup.py`

- Function: `ensure_collection(client, name: str, vector_size: int = 1024) -> None`
- Cohere embed-multilingual-v3.0 has **1024 dimensions**
- Use hybrid config: dense (cosine) + sparse (BM25 via Qdrant's built-in sparse vectors)
- Configure with HNSW: `m=16, ef_construct=128`
- Don't drop existing collections without `--reindex` flag

### `src/indexing/embedder.py`

- Wrap `cohere.ClientV2`
- Function: `embed_chunks(texts: list[str], input_type: Literal["search_document", "search_query"]) -> list[list[float]]`
- Always use `input_type="search_document"` during indexing
- Batch up to 96 texts per request (Cohere's limit)
- Implement simple exponential backoff for rate limits (max 3 retries)

### `src/indexing/indexer.py`

- Function: `index_chunks(chunks: list[Chunk], collection: str) -> None`
- Generate dense vectors via embedder
- Generate sparse vectors via Qdrant's built-in BM25 (use `FastEmbed` with `Qdrant/bm25` model, locally - no API call)
- Upsert with `chunk_id` as point ID
- Idempotent: same `chunk_id` overwrites

### `scripts/ingest.py`

CLI with `argparse`:
- `--scope` (required): `public` | `private`
- `--path` (optional): specific subfolder under `data/raw_pdfs/<scope>/`, default = all
- `--reindex` (flag): drop and recreate collection first
- `--dry-run` (flag): parse + chunk + log stats, but don't write to Qdrant

Output: progress bar (`tqdm`), summary at end (n files, n chunks, total tokens, time, estimated cost).

## Testing requirements

Write pytest tests for:

1. **`test_structure_detector.py`**: At minimum 8 test cases covering:
   - Standard "Άρθρο 23" detection
   - Article with letter suffix: "Άρθρο 23α"
   - Paragraph in different forms: "1.", "παρ. 4", "παράγραφος 4"
   - ΦΕΚ with different spacings: "ΦΕΚ Α' 167/2017", "Φ.Ε.Κ. Α 167/17"
   - Law number variants: "Ν. 4495/2017", "Νόμος 4495/2017", "Π.Δ. 696/74"
   - Negative cases: text mentioning "άρθρο" mid-sentence should NOT match start-of-article

2. **`test_chunker.py`**:
   - Article that fits → single chunk with article label
   - Article that exceeds limit → multiple paragraph-level chunks, all carrying same article
   - Paragraph exceeding limit → sentence split with overlap
   - Header context present on every chunk
   - chunk_id is deterministic (same input → same id)
   - Idempotent: chunking twice produces identical chunks

3. **`test_metadata_extractor.py`**:
   - Extract title from page 1 of a synthetic legal doc
   - Extract law number, ΦΕΚ, date
   - Handle missing fields gracefully (return None, not crash)

You don't need real PDFs for tests - create synthetic text fixtures that mimic the
structures. For an end-to-end smoke test, you can put 1-2 small sample PDFs in
`tests/fixtures/` if you find suitable public-domain ones.

## Acceptance criteria

Phase 1 is done when:

- [ ] `uv run pytest tests/` passes with all the tests listed above
- [ ] `uv run ruff check src/ scripts/ tests/` passes clean
- [ ] `uv run python scripts/ingest.py --scope public --dry-run` works without errors when given at least one PDF in `data/raw_pdfs/public/`
- [ ] After a real `ingest.py --scope public` run, the Qdrant dashboard (`http://localhost:6333/dashboard`) shows the `domiki_public` collection with points
- [ ] Re-running `ingest.py` produces zero new points (idempotent)
- [ ] `ingest.py` with no PDFs in folder logs a clear "no files found" message, exits 0

## Out of scope - DO NOT DO IN THIS PHASE

- Retrieval / search logic (Phase 2)
- Reranking (Phase 2)
- LLM calls anywhere in ingestion (no AI-based metadata, no AI-based chunking)
- OCR (we'll handle scanned PDFs later)
- Web scraping or URL ingestion
- Streamlit UI (Phase 3)
- FastAPI endpoints (later)
- Authentication
- Docker compose changes beyond what's already in `docker-compose.yml`
- Adding new top-level dependencies without explaining why first

## Implementation order

Suggest implementing in this order to allow incremental verification:

1. `models.py` (no deps)
2. `pdf_parser.py` + manual test with one PDF
3. `structure_detector.py` + tests
4. `metadata_extractor.py` + tests
5. `chunker.py` + tests
6. `pipeline.py` (combines 2-5 for one file)
7. `qdrant_setup.py` + verify with empty collection
8. `embedder.py` + manual test with 2-3 strings
9. `indexer.py` + integration test with 1 file
10. `scripts/ingest.py` + end-to-end test

After each step, run relevant tests before moving on.
