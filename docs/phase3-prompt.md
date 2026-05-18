# Phase 3: Generation + Streamlit UI

Read `CLAUDE.md` first for project context and conventions. Phases 1 and 2 are complete:
- 172 chunks in `domiki_public` with proper metadata
- Tokenizer parity (md5-based) between indexer and retriever
- Hybrid search + Cohere Rerank giving Recall@5 ≈ 73%, MRR ≈ 0.46
- `Retriever.search()` works end-to-end

## Goal of this phase

Connect a Claude LLM on top of the retriever to produce **grounded, cited, Greek-language answers** for civil engineers. Add a minimal Streamlit UI so a non-technical user can ask questions and see results.

End state: 
1. `uv run python scripts/ask.py "ερώτηση"` returns a complete answer with inline citations
2. `uv run streamlit run ui/streamlit_app.py` opens a web UI where engineer-user types question, sees answer + source chunks
3. The system **refuses to answer** when retrieved chunks don't contain enough info, instead of hallucinating

## Deliverables

```
src/generation/
├── models.py              # AnswerRequest, AnswerResponse, Citation pydantic models
├── prompts.py             # SYSTEM_PROMPT + ANSWER_TEMPLATE
├── claude_client.py       # Anthropic client wrapper, supports streaming
└── answer_generator.py    # AnswerGenerator class: take query + RankedHit[] → AnswerResponse

src/pipeline/
└── qa_pipeline.py         # QAPipeline class: combines Retriever + AnswerGenerator end-to-end

ui/
└── streamlit_app.py       # Main UI

scripts/
└── ask.py                 # CLI: ask question, get answer

tests/
├── test_prompts.py        # snapshot test on the system prompt
├── test_answer_generator.py
└── test_citations.py      # citations are properly extracted and well-formed
```

## Implementation specifications

### `src/generation/models.py`

```python
class Citation(BaseModel):
    chunk_id: str
    law_number: str | None
    article: str | None
    paragraph: str | None
    page_start: int
    page_end: int
    source_file: str
    # for display: a human-readable label like "Ν. 4495/2017, Άρθρο 100, σελ. 23"
    label: str

class AnswerResponse(BaseModel):
    query: str
    answer_text: str               # the natural language answer in Greek
    citations: list[Citation]       # all citations referenced in answer_text
    source_chunks: list[RankedHit]  # the chunks fed to the LLM
    refused: bool                   # True if model said "δεν έχω επαρκή πληροφορία"
    timing: dict[str, float]        # retrieval_ms, generation_ms, total_ms
    token_usage: dict[str, int]     # input_tokens, output_tokens
```

### `src/generation/prompts.py`

The system prompt is the most important piece of Phase 3. Use this **as-is** (do not paraphrase or shorten):

```
Είσαι εξειδικευμένος βοηθός για πολιτικούς μηχανικούς που εργάζονται με την ελληνική πολεοδομική και κατασκευαστική νομοθεσία. Απαντάς σε ερωτήσεις βάσει ΑΠΟΚΛΕΙΣΤΙΚΑ των νομοθετικών αποσπασμάτων που σου δίνονται.

ΑΥΣΤΗΡΟΙ ΚΑΝΟΝΕΣ:

1. ΧΡΗΣΗ ΠΗΓΩΝ
Βασίζεσαι ΑΠΟΚΛΕΙΣΤΙΚΑ στα αποσπάσματα που σου παρέχονται. Δεν χρησιμοποιείς γενική γνώση για ελληνική νομοθεσία. Αν κάποιο στοιχείο δεν εμφανίζεται στα αποσπάσματα, δεν το αναφέρεις.

2. CITATIONS - ΥΠΟΧΡΕΩΤΙΚΕΣ ΣΕ ΚΑΘΕ ΙΣΧΥΡΙΣΜΟ
Κάθε νομικός ισχυρισμός ΠΡΕΠΕΙ να συνοδεύεται από αναφορά στη μορφή:
[Source: chunk_id_X]
όπου X είναι ο αριθμός αποσπάσματος (π.χ. [Source: chunk_1], [Source: chunk_3]). Δεν επιτρέπονται ισχυρισμοί χωρίς αναφορά. Πολλαπλά αποσπάσματα στον ίδιο ισχυρισμό: [Source: chunk_1, chunk_2].

3. ΑΝ ΔΕΝ ΥΠΑΡΧΕΙ ΕΠΑΡΚΗΣ ΠΛΗΡΟΦΟΡΙΑ
Γράψε ρητά: "Δεν βρίσκω επαρκή πληροφορία στις διαθέσιμες πηγές για να απαντήσω σε αυτή την ερώτηση. Συνιστώ να συμβουλευτείτε εξειδικευμένο σύμβουλο ή το πλήρες κείμενο της νομοθεσίας."
Μην επιχειρείς να συνδυάσεις γενικές γνώσεις. Καλύτερα μια ειλικρινής άρνηση παρά μια λάθος απάντηση.

4. ΔΕΝ ΕΦΕΥΡΙΣΚΕΙΣ
- Δεν εφευρίσκεις άρθρα, παραγράφους, αριθμούς νόμων, ή ποσά
- Δεν συμπληρώνεις πληροφορίες που δεν υπάρχουν στα αποσπάσματα
- Δεν παραφράζεις τόσο ελεύθερα ώστε να αλλάζεις το νόημα

5. ΣΥΓΚΕΚΡΙΜΕΝΕΣ ΤΟΠΟΘΕΣΙΕΣ
Αν η ερώτηση αφορά συγκεκριμένο ακίνητο/τοποθεσία αλλά λείπουν στοιχεία (εντός/εκτός σχεδίου, ζώνη, ΓΠΣ, ειδικές περιοχές), ζήτα ρητά αυτές τις πληροφορίες πριν δώσεις οριστική απάντηση.

6. DISCLAIMER
Στο ΤΕΛΟΣ κάθε ουσιαστικής απάντησης πρόσθεσε ακριβώς:
---
ΣΗΜΕΙΩΣΗ: Η παρούσα απάντηση παρέχεται ως βοηθητικό εργαλείο και δεν αποτελεί νομική συμβουλή. Ο μηχανικός που χρησιμοποιεί την πληροφορία οφείλει να επαληθεύει τις διατάξεις από το πρωτότυπο κείμενο και να ζητά εξειδικευμένη συμβουλή όπου απαιτείται.

7. ΓΛΩΣΣΑ ΚΑΙ ΥΦΟΣ
- Πάντα ελληνικά
- Σαφή τεχνική γλώσσα για επαγγελματίες μηχανικούς
- Συγκεκριμένα ποσά, προθεσμίες, αριθμοί αν υπάρχουν στα αποσπάσματα
- Χωρίς bullet points για σύντομες απαντήσεις (πεζός λόγος). Bullet points μόνο για λίστες >3 στοιχείων.
- Δεν χρησιμοποιείς emoji
```

The user-turn template:

```
Ερώτηση: {query}

Διαθέσιμα αποσπάσματα:

{for i, hit in enumerate(hits)}
=== chunk_{i+1} ===
Πηγή: {hit.law_number} {hit.article} {hit.paragraph}
Σελίδες: {hit.page_start}-{hit.page_end}
Αρχείο: {hit.source_file}

{hit.text}
===

Παρακαλώ απάντησε στην ερώτηση βάσει αποκλειστικά των παραπάνω αποσπασμάτων.
```

### `src/generation/claude_client.py`

Wrap `anthropic.Anthropic` with:
- `generate(system, user, max_tokens=2048, stream=False) -> str | Iterator[str]`
- Use the model from `settings.claude_model` (currently `claude-sonnet-4-6`)
- Track input/output tokens for cost reporting
- Retry once on transient errors, then raise

### `src/generation/answer_generator.py`

```python
class AnswerGenerator:
    def __init__(self, claude_client: ClaudeClient): ...
    
    def generate(
        self,
        query: str,
        hits: list[RankedHit],
        stream: bool = False,
    ) -> AnswerResponse | Iterator[str]:
        # 1. Build prompts from template
        # 2. Call Claude
        # 3. Parse citations from response (regex on [Source: chunk_X])
        # 4. Build AnswerResponse with Citation objects, refused flag, timings
        ...
```

**Citation parsing**: extract all `[Source: chunk_N]` (or comma-separated multiple) markers from the answer text. Map each chunk_N back to the corresponding hit and create a `Citation` object. Citations in the answer text stay as-is — UI will format them; do not rewrite the text.

**Refused detection**: if the answer text contains "Δεν βρίσκω επαρκή πληροφορία" exactly, set `refused = True`.

### `src/pipeline/qa_pipeline.py`

```python
class QAPipeline:
    def __init__(self, retriever: Retriever, generator: AnswerGenerator): ...
    
    def ask(
        self,
        query: str,
        top_k: int = 8,    # how many chunks to send to LLM
        stream: bool = False,
    ) -> AnswerResponse | Iterator[str]:
        # 1. retriever.search(query, top_k=top_k)
        # 2. answer_generator.generate(query, hits)
        # 3. return response
```

8 chunks is a good default — enough context, not overwhelming for Sonnet.

### `ui/streamlit_app.py`

Single-page Streamlit app, sections top-to-bottom:

**Header**
- Title: "Domiki RAG - Βοηθός Πολεοδομικής Νομοθεσίας"
- One-line description
- Persistent warning banner: "Demo / personal use. Verify all answers with primary sources."

**Query input**
- Large `st.text_area` for the question (placeholder example: "Μπορώ να χτίσω πισίνα σε εκτός σχεδίου ακίνητο 2 στρ. με Σ.Δ. 0.4;")
- "Submit" button

**Answer section** (after submit)
- Stream the answer as it's generated (use `st.write_stream`)
- After streaming completes, replace inline `[Source: chunk_N]` markers with subtle clickable references using markdown
- Show "Refused" banner if `refused=True`
- Show disclaimer always

**Sources section** (collapsible expander, default closed)
- Each source as a card showing: law_number, article, page, rerank_score, text (first 300 chars + "show more")

**Footer / debug**
- Timing breakdown (retrieval / generation / total)
- Token usage + estimated cost

Keep styling minimal — no custom CSS, use Streamlit defaults.

### `scripts/ask.py`

```
Usage: ask.py "query" [--top-k N] [--no-stream] [--json]

Output (default): natural language answer with citations, then a "Sources" section.
With --json: dumps the AnswerResponse pydantic model as JSON.
```

## Acceptance criteria

Phase 3 is done when:

- [ ] `uv run pytest tests/` — all pass
- [ ] `uv run ruff check src/ scripts/ tests/ ui/` — clean
- [ ] `uv run python scripts/ask.py "διαδικασία υπαγωγής αυθαιρέτου"` returns a Greek answer with at least 2 properly-formatted citations
- [ ] When asked a question with no relevant data (e.g. "ποιες οι προδιαγραφές για αεροδρόμια στην Κρήτη"), the model correctly refuses with the standard phrase
- [ ] `streamlit run ui/streamlit_app.py` opens browser, accepts query, streams answer, shows sources
- [ ] Disclaimer appears in EVERY substantive answer
- [ ] Citations parse correctly — running `test_citations.py` with a snapshot answer extracts all sources
- [ ] No "Source: chunk_X" or any other untransformed marker shown in the UI's natural-language answer (UI replaces them with proper formatting)

## Cost budget

For Phase 3 dev itself: ~3-5$ Anthropic API. Each test query: ~0.01-0.05$ (8 chunks ~3-4K input tokens, 500-1500 output tokens).

## Out of scope — DO NOT DO IN THIS PHASE

- User authentication / multi-user
- Chat history / conversation memory (each query is independent)
- File upload for new documents
- Re-indexing from UI
- FastAPI backend (Streamlit is enough for MVP)
- Production deployment / Docker for the app
- A/B testing different system prompts (just use the one given)
- Advanced features like "follow-up question with context"

## Implementation order

1. `src/generation/models.py`
2. `src/generation/prompts.py` (paste the prompt verbatim)
3. `src/generation/claude_client.py` + simple test calling Sonnet
4. `src/generation/answer_generator.py` with citation parsing
5. Tests for citation parsing on synthetic answers
6. `src/pipeline/qa_pipeline.py`
7. `scripts/ask.py` and validate output on 3-4 real queries
8. `ui/streamlit_app.py` (basic version first, then polish)
9. Final end-to-end smoke test

Before writing code, ask any clarifying questions about the system prompt, citation format, or UI structure if anything seems off.
