# Domiki RAG

**Βοηθός Ελληνικής Πολεοδομικής Νομοθεσίας** — Q&A σύστημα πάνω σε ελληνικές πολεοδομικές και κατασκευαστικές νόμους για πολιτικούς μηχανικούς, αρχιτέκτονες και τεχνικούς επαγγελματίες.

> **⚠ Beta / Research Tool** — Αυτό το εργαλείο παρέχεται αποκλειστικά για ερευνητική και προσωπική χρήση. Δεν αποτελεί νομική συμβουλή. Επαληθεύετε πάντα τα αποτελέσματα με τις πρωτογενείς πηγές (ΦΕΚ, επίσημα κείμενα νόμων).

## Τι κάνει

Χρησιμοποιεί RAG (Retrieval-Augmented Generation) αρχιτεκτονική:
1. **Retrieval** — υβριδική αναζήτηση (dense Cohere + sparse BM25) σε Qdrant vector DB
2. **Reranking** — Cohere Rerank 3 για ακρίβεια
3. **Generation** — Claude (Anthropic) δημιουργεί τεκμηριωμένη απάντηση με υποχρεωτικές αναφορές σε άρθρα και σελίδες

## Status

- [x] Φάση 1: Ingestion (PDF → chunks + metadata)
- [x] Φάση 2: Retrieval (hybrid search + reranking)
- [x] Φάση 3: Generation + Streamlit UI
- [x] Φάση 4: Query logging, history, feedback, admin view, site password gate
- [ ] Φάση 5: Evaluation iteration & scale

## Προαπαιτούμενα

- Python 3.11+
- Docker Desktop (για local Qdrant)
- API keys: [Anthropic](https://console.anthropic.com), [Cohere](https://cohere.com)

## Local Development Setup

### 1. Εγκατάσταση `uv`

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Mac/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Sync dependencies

```bash
cd domiki-rag
uv sync
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

Required vars:
```
ANTHROPIC_API_KEY=sk-ant-...
COHERE_API_KEY=...
SITE_PASSWORD=<your-beta-password>
ADMIN_PASSWORD=<your-admin-password>
```

### 4. Start local Qdrant

```bash
docker compose up -d
```

Dashboard: `http://localhost:6333/dashboard`

### 5. Verify setup

```bash
uv run python scripts/verify_setup.py
```

### 6. Run the app

```bash
uv run streamlit run ui/streamlit_app.py
```

### 7. CLI usage

```bash
uv run python scripts/ask.py "Πώς υπολογίζεται το πρόστιμο αυθαίρετης κατασκευής;"
```

## Project Structure

```
domiki-rag/
├── src/
│   ├── ingestion/       # PDF → chunks + metadata
│   ├── indexing/        # Embeddings + Qdrant upsert
│   ├── retrieval/       # Hybrid search + reranking
│   ├── generation/      # Claude prompts + citations
│   ├── pipeline/        # QA orchestration
│   ├── observability/   # Query logging (SQLite)
│   └── common/          # Shared tokenizer
├── ui/
│   ├── streamlit_app.py # Main UI (site-password gated)
│   └── pages/
│       └── 1_Admin.py   # Admin view (admin-password gated)
├── scripts/
│   ├── ask.py           # CLI Q&A
│   ├── ingest.py        # Ingest PDFs
│   ├── migrate_to_cloud.py  # Copy local Qdrant → cloud
│   └── verify_setup.py  # Pre-flight checks
├── tests/               # Pytest test suite (142 tests)
├── data/
│   ├── raw_pdfs/
│   │   ├── public/      # Public sources (ΦΕΚ) — safe to commit metadata
│   │   └── private/     # Subscription content (gitignored, personal use only)
│   ├── processed/       # Parsed chunks (gitignored)
│   ├── qdrant/          # Vector DB storage (gitignored)
│   └── eval/            # Evaluation test cases
├── docker-compose.yml
└── pyproject.toml
```

## Running Tests

```bash
uv run pytest tests/
```

## Legal & Privacy Notes

- `data/raw_pdfs/private/` contains material from subscription services and is **personal use only** — never committed, never distributed.
- The two Qdrant collections (`domiki_public` and `domiki_private`) are kept physically separate.
- **This is NOT legal advice.** Every answer includes source citations for your own verification. Always consult a licensed engineer or lawyer for official guidance.
- Results depend on which documents have been indexed; the system does not have access to all Greek legislation.

## License

All rights reserved. See [LICENSE](LICENSE).
