# Domiki RAG - Project Context for Claude Code

## What this is
Q&A system over Greek construction/urban planning legislation. RAG (Retrieval-Augmented
Generation) architecture. End users are civil engineers asking natural-language questions
("can I build a pool at location X with these zoning params?") and getting answers grounded
in cited legislation.

## Current phase
**Phase 1: Ingestion** (parser, chunker, indexer)

Phase 0 (setup) is complete. Phase 2+ (retrieval, generation, UI) come later.

## Tech stack
- **Python 3.11+**, managed by `uv` (NOT pip/poetry/conda)
- **LlamaIndex** as RAG framework
- **Qdrant** as vector DB (runs in Docker locally on `localhost:6333`)
- **Cohere** for embeddings (`embed-multilingual-v3.0`) and reranking (`rerank-multilingual-v3.0`)
- **Claude API** (Anthropic) for generation - model: `claude-sonnet-4-6`
- **PyMuPDF (fitz)** primary PDF parser, **pdfplumber** for tables
- **Streamlit** for early UI, **FastAPI** for later backend
- **pydantic v2** for all structured data

## Project structure
```
domiki-rag/
├── src/
│   ├── config.py          # pydantic-settings, reads .env
│   ├── ingestion/         # PDF → chunks + metadata (Phase 1)
│   ├── indexing/          # Embeddings + Qdrant (Phase 1)
│   ├── retrieval/         # Hybrid search + rerank (Phase 2)
│   ├── generation/        # Claude prompts + citations (Phase 3)
│   └── api/               # FastAPI (Phase 6+)
├── ui/                    # Streamlit (Phase 3)
├── scripts/               # CLI tools (ingest, verify, eval)
├── tests/                 # pytest
└── data/
    ├── raw_pdfs/
    │   ├── public/        # Public sources (ΦΕΚ, εγκύκλιοι, ΣτΕ) - safe to commit metadata
    │   └── private/       # Personal subscription content (NEVER commit, NEVER include in commercial export)
    ├── processed/         # Intermediate parsed text + JSON metadata
    └── eval/              # Test cases for evaluation
```

## Conventions (strict)

### Python style
- Python 3.11 syntax: `list[str]`, `X | None`, NOT `List[str]` / `Optional[X]`
- All public functions have type hints
- Use `pathlib.Path`, NOT `os.path`
- Use `pydantic.BaseModel` for ALL structured data (chunks, metadata, configs)
- Use stdlib `logging` for logs, NEVER `print()` in `src/` (OK in `scripts/`)
- All errors raised with informative messages, never bare `raise`
- Imports: `from src.module import X` (src is the package)

### Language conventions (bilingual codebase)
- All code identifiers in English (class/function/variable names)
- Domain terms in Greek allowed in strings/comments: "ΦΕΚ", "άρθρο", "παράγραφος", "εδάφιο"
- Comments and docstrings: English preferred, Greek OK for domain explanation
- User-facing strings (CLI output, errors visible to engineer-user, UI labels): **Greek**

### Greek text handling (critical)
- Always normalize Unicode to NFC form before processing: `unicodedata.normalize("NFC", text)`
- Handle final sigma correctly: ς (end of word) vs σ (elsewhere). Greek regex should not assume one form.
- Tonos variants: ά/ὰ/ᾱ - normalize. Use `unicodedata.normalize` + lowercase carefully (lower() converts Σ→σ which is wrong for word-final positions; use `.casefold()` for comparisons, not lowercase).
- Avoid splitting words that contain Greek hyphens or accented characters across chunks.

### Tooling
- Format/lint: `uv run ruff check --fix src/ scripts/ tests/`
- Test: `uv run pytest tests/`
- Run a script: `uv run python scripts/<name>.py`

## Critical constraints

### Legal / business
- Current scope: **personal and family use only**. Do not add multi-tenant, billing, or commercial features yet.
- Content in `data/raw_pdfs/private/` is from a paid subscription and stays local. Code must not transmit private content to external services beyond the explicit API calls (Cohere embed, Claude generate). NO telemetry, NO automatic uploads.
- The two collections (`domiki_public` and `domiki_private`) must remain physically separated. The commercial future-version will only ship the public collection.

### Quality
- **Citations are mandatory** in every retrieval-stage output. Each chunk stored in Qdrant must have enough metadata to construct a citation (source file, page, άρθρο/παρ. if known).
- **Never strip metadata** during chunking. If a chunk has no detected άρθρο, mark it `null`, do not skip the field.
- **Never invent metadata** that wasn't in the source. Better to have `law_number=null` than `law_number="Ν. ???/????"`.

### Out of scope reminders
- Do NOT scrape websites. All ingestion is from local PDFs.
- Do NOT add web search to ingestion.
- Do NOT add LLM calls in the ingestion path (no AI-generated metadata, no LLM-based chunking in Phase 1).
- Do NOT modify `src/config.py` to add fields without good reason.

## Verifying setup before starting
Before any Phase 1 work, run `uv run python scripts/verify_setup.py` to confirm Qdrant
is up and API keys are working. If anything fails there, fix it first.
