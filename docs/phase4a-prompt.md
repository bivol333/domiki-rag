# Phase 4a: Query Logging + History + Admin View + Feedback

Read `CLAUDE.md` first for project context. Phases 0-3 are complete. The system has:
- Working RAG with hybrid search + rerank + Cohere/Claude APIs
- `QAPipeline` orchestrating retrieval + generation
- Streamlit UI at `ui/streamlit_app.py`
- 110 tests passing

## Goal of this phase

Add minimal observability so the developer (admin) can review queries and answers, and beta users get a smoother experience with history and feedback.

**Scope: as simple as possible.** No analytics, no metrics dashboards, no user identification, no privacy notices. Just enough to evaluate RAG output quality during beta testing.

## End state

- Every query logged to SQLite with the answer, chunks used, refused flag, and optional feedback
- Beta user sees their last 20 queries in a sidebar (per browser, via cookie)
- Beta user can click thumbs up/down + leave optional comment
- Admin opens separate password-protected Streamlit page to review all queries
- Welcome screen shows 3 sample questions if no history yet
- All this works in the existing Streamlit app

## Critical constraints

1. **No user identification**. Just an anonymous browser session_id (UUID stored in cookie). The system MUST work without users entering any personal info.
2. **No latency/cost/token metrics in admin view**. Keep it minimal - just enough for debug/evaluation.
3. **Browser cookie history only**. Don't try to persist across devices. If user clears cookies, history resets. That's fine.
4. **Don't break existing functionality**. All 110 existing tests must still pass after refactor.

## Deliverables

```
src/observability/
├── __init__.py
├── database.py            # SQLite connection + schema setup
├── models.py              # QueryLogEntry pydantic model
└── logger.py              # QueryLogger class

ui/
├── streamlit_app.py       # MODIFY: cookie init, sidebar history, feedback widget, welcome screen
└── pages/
    └── 1_Admin.py         # NEW: admin page with password gate (Streamlit auto-discovers `pages/` folder)

src/pipeline/
└── qa_pipeline.py         # MODIFY: accept session_id, integrate QueryLogger, return query_id

tests/
├── test_query_logger.py
└── test_admin_page.py     # if practical to test multipage; otherwise smoke test only

scripts/
└── init_db.py             # one-time DB initialization script
```

Add new dependencies to `pyproject.toml`:
- `streamlit-cookies-controller` (for cookie management) — verify exact package name on PyPI before adding; alternative is `streamlit-extra-cookies` or `extra-streamlit-components`. Pick the most maintained one.

## Implementation specifications

### `src/observability/database.py`

SQLite DB at `data/logs.db` (gitignored). Schema:

```sql
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,           -- ISO 8601
    session_id TEXT NOT NULL,          -- UUID from browser cookie
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    chunks_used TEXT NOT NULL,         -- JSON: [{"chunk_id": "...", "article": "...", "law_number": "..."}, ...]
    refused INTEGER NOT NULL,          -- 0 or 1
    feedback TEXT,                     -- 'positive' | 'negative' | NULL
    feedback_comment TEXT              -- free text or NULL
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON queries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_session ON queries(session_id);
CREATE INDEX IF NOT EXISTS idx_refused ON queries(refused);
CREATE INDEX IF NOT EXISTS idx_feedback ON queries(feedback);
```

Provide a `get_connection()` function with sensible defaults (timeout, journal_mode WAL). Add `init_db()` function called from `scripts/init_db.py`.

### `src/observability/models.py`

```python
class QueryLogEntry(BaseModel):
    id: int | None = None
    timestamp: datetime
    session_id: str
    query: str
    answer: str
    chunks_used: list[dict]      # serialized as JSON in DB
    refused: bool
    feedback: Literal["positive", "negative"] | None = None
    feedback_comment: str | None = None
```

### `src/observability/logger.py`

```python
class QueryLogger:
    def __init__(self, db_path: Path = Path("data/logs.db")):
        self.db_path = db_path
        # ensure DB exists, run init_db() if not

    def log(
        self,
        session_id: str,
        query: str,
        response: AnswerResponse,
    ) -> int:
        """Insert query+answer, return query_id."""
        ...

    def add_feedback(
        self,
        query_id: int,
        feedback: Literal["positive", "negative"],
        comment: str | None = None,
    ) -> None:
        ...

    def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[QueryLogEntry]:
        """Most recent first."""
        ...

    def get_all_queries(
        self,
        limit: int = 100,
        offset: int = 0,
        refused_only: bool = False,
        feedback_filter: Literal["positive", "negative", None] = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[QueryLogEntry]:
        """For admin view."""
        ...

    def count_total(self, **filters) -> int:
        """For pagination."""
        ...
```

### `src/pipeline/qa_pipeline.py` modifications

Update `QAPipeline.ask()` and `ask_stream()`/`finalize_stream()` to:
1. Accept an optional `session_id: str | None = None` parameter
2. Inject a `QueryLogger` (default in __init__, can be replaced for tests)
3. After generating `AnswerResponse`, call `logger.log(session_id, query, response)` if session_id is provided
4. Return both the response and the query_id (tuple or attach to response)

Suggested signature:
```python
def ask(self, query: str, session_id: str | None = None, top_k: int = 8) -> tuple[AnswerResponse, int | None]:
    # returns (response, query_id_if_logged_else_None)
```

For streaming variants, return query_id from `finalize_stream` similarly.

### `ui/streamlit_app.py` modifications

**Cookie setup (top of main):**
```python
from streamlit_cookies_controller import CookieController  # or equivalent
cookies = CookieController()
session_id = cookies.get("session_id")
if not session_id:
    session_id = str(uuid.uuid4())
    cookies.set("session_id", session_id, max_age=60*60*24*365)  # 1 year
```

**Welcome screen** (shown when sidebar history is empty):
- Heading: "Καλώς ήρθατε στον Δομικό RAG"
- One paragraph intro: "Αυτό είναι ένα βοηθητικό εργαλείο για ερωτήματα ελληνικής πολεοδομικής νομοθεσίας. Πληκτρολογήστε ερώτηση ή δοκιμάστε ένα από τα παρακάτω."
- 3 sample question buttons:
  1. "Πώς υπολογίζεται το πρόστιμο για αυθαίρετη κατασκευή κατηγορίας 3;"
  2. "Ποιες κατασκευές μπορούν να υπαχθούν στον νόμο 4495/2017;"
  3. "Διαδικασία υπαγωγής αυθαιρέτου σε αρχαιολογικό χώρο ζώνης Α"

Click a sample → fills the query input and submits.

**Sidebar history:**
- Heading: "Πρόσφατες ερωτήσεις"
- List last 20 queries from `logger.get_session_history(session_id)`
- Each entry: truncated query (60 chars) + timestamp short form
- Click → re-runs the query showing the cached answer (read from DB, don't re-execute the pipeline)

**Feedback widget** (after each answer):
- Two buttons side by side: "👍 Σωστή απάντηση" and "👎 Λάθος/Ελλιπής"
- Click either → small textarea appears: "Σχόλιο (προαιρετικά)"
- Submit button below textarea: "Καταγραφή"
- After submission, replace widget with: "Ευχαριστούμε για το feedback!"
- State persists in session_state per query_id

### `ui/pages/1_Admin.py`

Streamlit auto-discovers files in `ui/pages/` as multipages. This file becomes accessible at `/Admin` route in the sidebar.

**Password gate:**
```python
admin_password = st.secrets.get("ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
entered = st.text_input("Admin password", type="password")
if entered != admin_password:
    st.error("Λάθος password")
    st.stop()
```

**After auth, layout:**

Filters at top (sidebar):
- Show refused only (checkbox)
- Feedback filter (radio: all / positive / negative / no feedback)
- Date range (last 24h / last 7 days / last 30 days / all)
- Reload button

Main area:
- Table-like list of queries, most recent first, 50 per page
- Each row shows: timestamp (short), query (truncated 100 chars), refused indicator, feedback indicator
- Click row → expand to show:
  - Full query
  - Full answer
  - Chunks used (article names + chunk_ids)
  - Feedback + comment (if any)
- Pagination at bottom (Previous / Next / page indicator)

**No CSV export, no charts.** Just the table. Keep it minimal.

### `scripts/init_db.py`

Simple one-time script:
```python
"""Initialize the SQLite database for query logs."""
from src.observability.database import init_db

if __name__ == "__main__":
    init_db()
    print("Database initialized at data/logs.db")
```

## Testing requirements

`tests/test_query_logger.py`:
1. Insert + retrieve roundtrip
2. Session history filtering works
3. Add feedback updates existing row
4. Admin filters (refused_only, feedback, date range) all work
5. Pagination (limit + offset) works
6. JSON serialization of chunks_used roundtrips
7. Multiple sessions don't leak history to each other

`tests/test_admin_page.py`:
- Smoke test: page loads, password gate works
- Don't try to test full UI interactions (Streamlit UI testing is painful)

## Acceptance criteria

Phase 4a is done when:

- [ ] All 110 existing tests still pass
- [ ] New logger tests pass (at least 7 covering the cases above)
- [ ] `uv run python scripts/init_db.py` creates `data/logs.db`
- [ ] Running the main Streamlit app: query goes through, gets logged, appears in sidebar history immediately
- [ ] Click a history entry → shows the cached answer (verify by checking it doesn't take 30s, i.e. no LLM call)
- [ ] Feedback widget: thumbs + comment + submit → DB row updated correctly
- [ ] Admin page at `/Admin` requires password, then shows queries with working filters
- [ ] First visit (no cookie) shows welcome screen with 3 sample questions; clicking one fills + submits
- [ ] Browser refresh preserves session_id (cookie works)
- [ ] Two different browser sessions see different histories

## Out of scope - DO NOT DO

- User identification or naming
- Privacy notice or GDPR features
- Latency / cost / token tracking in admin
- CSV/JSON export from admin (defer to later phase)
- Charts or analytics
- Rate limiting (handled by Anthropic spending cap)
- Site-wide password (that's Phase 4b)
- Deployment configuration (that's Phase 4c)

## Implementation order

1. `database.py` + schema + `init_db.py`
2. `models.py`
3. `logger.py` + tests
4. `qa_pipeline.py` modifications (preserving existing tests)
5. `streamlit_app.py` - cookie init only, verify
6. `streamlit_app.py` - sidebar history
7. `streamlit_app.py` - welcome screen + sample questions
8. `streamlit_app.py` - feedback widget
9. `pages/1_Admin.py`
10. Final smoke test of the whole flow

Verify existing tests still pass after each major step before moving on.

Ask clarifying questions before coding if anything is unclear, especially around:
- Which cookie library to use (verify availability and maintenance status on PyPI)
- Streamlit multipage app structure
- How to handle the session_id when running from `scripts/ask.py` (CLI doesn't have a browser session - use a fixed CLI session_id like "cli-{hostname}")
