# Domiki RAG

Σύστημα Q&A πάνω σε ελληνική πολεοδομική/κατασκευαστική νομοθεσία για πολιτικούς μηχανικούς.
RAG (Retrieval-Augmented Generation) αρχιτεκτονική με δημόσιες πηγές + προσωπικές σημειώσεις.

## Status: Φάση 0 - Setup

## Προαπαιτούμενα

- Python 3.11+
- Docker Desktop εγκατεστημένο και να τρέχει
- API keys:
  - Anthropic (console.anthropic.com)
  - Cohere (cohere.com)

## Setup βήμα-βήμα

### 1. Εγκατάσταση `uv` (modern Python package manager)

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

Αυτό φτιάχνει αυτόματα το `.venv` και κατεβάζει όλες τις εξαρτήσεις.

### 3. Configure environment

```bash
cp .env.example .env
```

Άνοιξε το `.env` και βάλε τα δικά σου API keys.

### 4. Ξεκίνα το Qdrant με Docker

```bash
docker compose up -d
```

Έλεγχος ότι τρέχει: άνοιξε browser στο `http://localhost:6333/dashboard`

### 5. Επαλήθευση setup

```bash
uv run python scripts/verify_setup.py
```

Αν όλα είναι πράσινα, είσαι έτοιμος για Φάση 1.

## Project Structure

```
domiki-rag/
├── src/
│   ├── ingestion/      # PDF → chunks + metadata
│   ├── indexing/       # Embeddings + vector store
│   ├── retrieval/      # Hybrid search + reranking
│   ├── generation/     # Claude prompts + citations
│   └── api/            # FastAPI endpoints (αργότερα)
├── ui/                 # Streamlit UI
├── scripts/            # Utility scripts (ingest, verify, eval)
├── tests/              # Pytest tests
├── data/
│   ├── raw_pdfs/
│   │   ├── public/     # Δημόσιες πηγές (ΦΕΚ, εγκύκλιοι)
│   │   └── private/    # Domiki content (gitignored, personal only)
│   ├── processed/      # Parsed text + metadata
│   ├── qdrant/         # Qdrant persistent storage
│   └── eval/           # Test cases
├── docker-compose.yml  # Qdrant container
├── pyproject.toml      # Dependencies
└── .env                # API keys (gitignored)
```

## Roadmap

- [x] Φάση 0: Setup (αυτό)
- [ ] Φάση 1: Ingestion MVP
- [ ] Φάση 2: Retrieval MVP
- [ ] Φάση 3: Generation + UI MVP
- [ ] Φάση 4: Evaluation framework
- [ ] Φάση 5: Iteration & scale

## Σημαντικές σημειώσεις

**Νομικά**: Το `data/raw_pdfs/private/` περιέχει υλικό από συνδρομητικές πηγές
(Δομική Πληροφορική) και είναι **personal use only**. Δεν διανέμεται, δεν
γίνεται commit, δεν συμπεριλαμβάνεται σε εμπορική έκδοση.

**Disclaimer**: Το σύστημα είναι assistant tool, όχι authoritative source.
Κάθε απάντηση περιλαμβάνει citations για επαλήθευση.
