"""Streamlit UI for Domiki RAG."""
import asyncio
import os
import re
import uuid
from datetime import datetime

import extra_streamlit_components as stx
import streamlit as st

from src.generation.answer_generator import AnswerGenerator
from src.generation.claude_client import ClaudeClient
from src.generation.models import AnswerResponse
from src.observability.logger import QueryLogger
from src.observability.models import QueryLogEntry
from src.pipeline.qa_pipeline import QAPipeline
from src.retrieval.retriever import Retriever

_CITATION_RE = re.compile(r"\[Source:\s*((?:chunk_\d+\s*,?\s*)+)\]", re.IGNORECASE)
_CHUNK_NUM_RE = re.compile(r"chunk_(\d+)", re.IGNORECASE)

_SAMPLE_QUESTIONS = [
    "Πώς υπολογίζεται το πρόστιμο για αυθαίρετη κατασκευή κατηγορίας 3;",
    "Ποιες κατασκευές μπορούν να υπαχθούν στον νόμο 4495/2017;",
    "Διαδικασία υπαγωγής αυθαιρέτου σε αρχαιολογικό χώρο ζώνης Α",
]


# ---------- resource bootstrapping ----------

@st.cache_resource
def _get_cookie_manager() -> stx.CookieManager:
    return stx.CookieManager(key="domiki_cookies")


@st.cache_resource
def _get_query_logger() -> QueryLogger:
    return QueryLogger()


@st.cache_resource
def _get_pipeline() -> QAPipeline:
    return QAPipeline(
        retriever=Retriever(),
        generator=AnswerGenerator(ClaudeClient()),
        query_logger=_get_query_logger(),
    )


# ---------- helpers ----------

def _replace_citations_for_display(text: str) -> str:
    def _to_super(match: re.Match) -> str:
        nums = [int(m.group(1)) for m in _CHUNK_NUM_RE.finditer(match.group(1))]
        if not nums:
            return ""
        joined = ",".join(str(n) for n in nums)
        return f"<sup>[{joined}]</sup>"
    return _CITATION_RE.sub(_to_super, text)


def _short_ts(dt: datetime) -> str:
    return dt.strftime("%d/%m %H:%M")


def _truncate(text: str, width: int) -> str:
    return text[:width] + "…" if len(text) > width else text


# ---------- cookie / session ----------

def _ensure_session_id() -> str:
    """Get session_id from cookie or mint a new one. Stored in session_state to
    survive the inter-render flicker while the cookie is being written."""
    if "session_id" in st.session_state:
        return st.session_state.session_id

    cookies = _get_cookie_manager()
    sid = cookies.get("session_id")
    if not sid:
        sid = str(uuid.uuid4())
        cookies.set("session_id", sid, max_age=365 * 24 * 60 * 60)
    st.session_state.session_id = sid
    return sid


# ---------- rendering ----------

def _render_welcome(sample_clicked_key: str) -> None:
    st.markdown("### Καλώς ήρθατε στον Δομικό RAG")
    st.write(
        "Αυτό είναι ένα βοηθητικό εργαλείο για ερωτήματα ελληνικής πολεοδομικής "
        "νομοθεσίας. Πληκτρολογήστε ερώτηση ή δοκιμάστε ένα από τα παρακάτω."
    )
    for i, sample in enumerate(_SAMPLE_QUESTIONS):
        if st.button(sample, key=f"sample_{i}", use_container_width=True):
            st.session_state[sample_clicked_key] = sample
            st.rerun()


def _render_feedback_widget(query_id: int, logger: QueryLogger) -> None:
    """Two-step feedback UX: click thumb → comment textarea → submit."""
    fb_state_key = f"fb_state_{query_id}"
    fb_done_key = f"fb_done_{query_id}"

    if st.session_state.get(fb_done_key):
        st.success("Ευχαριστούμε για το feedback!")
        return

    selected = st.session_state.get(fb_state_key)

    if selected is None:
        col1, col2, _ = st.columns([1, 1, 4])
        with col1:
            if st.button("👍 Σωστή απάντηση", key=f"thumbs_up_{query_id}"):
                st.session_state[fb_state_key] = "positive"
                st.rerun()
        with col2:
            if st.button("👎 Λάθος / Ελλιπής", key=f"thumbs_down_{query_id}"):
                st.session_state[fb_state_key] = "negative"
                st.rerun()
        return

    label = "✓ Σωστή" if selected == "positive" else "✗ Λάθος / Ελλιπής"
    st.caption(f"Επιλέξατε: {label}")
    comment = st.text_area("Σχόλιο (προαιρετικά)", key=f"comment_{query_id}", height=80)
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Καταγραφή", key=f"submit_fb_{query_id}", type="primary"):
            logger.add_feedback(query_id, selected, comment.strip() or None)
            st.session_state[fb_done_key] = True
            st.rerun()
    with col2:
        if st.button("Άκυρο", key=f"cancel_fb_{query_id}"):
            st.session_state.pop(fb_state_key, None)
            st.rerun()


def _render_source_list_from_metadata(chunks: list[dict]) -> None:
    """Compact source list rendered from logged metadata (no full text available)."""
    if not chunks:
        return
    with st.expander(f"Πηγές ({len(chunks)})", expanded=False):
        for i, c in enumerate(chunks, 1):
            parts = [p for p in (c.get("law_number"), c.get("article"), c.get("paragraph")) if p]
            header = " · ".join(parts) if parts else "(χωρίς μεταδεδομένα)"
            page_start = c.get("page_start")
            page_end = c.get("page_end")
            pages = (
                f"σελ. {page_start}-{page_end}"
                if page_start is not None and page_end is not None and page_end != page_start
                else (f"σελ. {page_start}" if page_start is not None else "")
            )
            st.markdown(f"**[{i}]** {header}  ·  {pages}")
            file = c.get("source_file") or "—"
            score = c.get("rerank_score")
            st.caption(
                f"Αρχείο: {file}"
                + (f"  ·  rerank_score: {score:.3f}" if score is not None else "")
            )
            st.divider()


def _render_live_source_cards(response: AnswerResponse) -> None:
    """Full source-card view for a fresh response (has chunk text)."""
    if not response.source_chunks:
        return
    with st.expander(f"Πηγές ({len(response.source_chunks)})", expanded=False):
        for i, rh in enumerate(response.source_chunks, 1):
            h = rh.hit
            parts = [p for p in (h.law_number, h.article, h.paragraph) if p]
            header = " · ".join(parts) if parts else "(χωρίς μεταδεδομένα)"
            pages = (
                f"σελ. {h.page_start}-{h.page_end}"
                if h.page_start is not None and h.page_end is not None
                and h.page_end != h.page_start
                else (f"σελ. {h.page_start}" if h.page_start is not None else "")
            )
            st.markdown(f"**[{i}]** {header}  ·  {pages}")
            st.caption(
                f"Αρχείο: {h.source_file or '—'}  ·  rerank_score: {rh.rerank_score:.3f}"
            )
            text = h.text or ""
            if len(text) > 300:
                with st.expander("Πλήρες κείμενο αποσπάσματος"):
                    st.text(text)
                st.text(text[:300] + "…")
            else:
                st.text(text)
            st.divider()


def _render_response_body(response: AnswerResponse) -> None:
    if response.refused:
        st.warning("⚠ Το σύστημα αρνήθηκε να απαντήσει — οι διαθέσιμες πηγές δεν επαρκούν.")
    if response.has_invalid_citations:
        st.info(
            "Σημείωση: το μοντέλο αναφέρθηκε σε απόσπασμα που δεν παρασχέθηκε. "
            "Αυτές οι αναφορές έχουν αντικατασταθεί με «[αναφορά μη διαθέσιμη]»."
        )

    st.markdown(_replace_citations_for_display(response.answer_text), unsafe_allow_html=True)
    _render_live_source_cards(response)


def _render_cached_entry(entry: QueryLogEntry, logger: QueryLogger) -> None:
    st.markdown(f"### {entry.query}")
    st.caption(f"Αποθηκευμένη ερώτηση · {_short_ts(entry.timestamp)}")
    if entry.refused:
        st.warning("⚠ Το σύστημα είχε αρνηθεί να απαντήσει σε αυτή την ερώτηση.")
    st.markdown(
        _replace_citations_for_display(entry.answer),
        unsafe_allow_html=True,
    )
    _render_source_list_from_metadata(entry.chunks_used)

    if entry.feedback:
        label = "👍 Σωστή" if entry.feedback == "positive" else "👎 Λάθος / Ελλιπής"
        st.caption(f"Καταγραμμένο feedback: {label}")
        if entry.feedback_comment:
            st.caption(f"Σχόλιο: {entry.feedback_comment}")
    else:
        st.divider()
        st.caption("Feedback")
        _render_feedback_widget(entry.id, logger)


def _render_sidebar_history(
    session_id: str, logger: QueryLogger,
) -> list[QueryLogEntry]:
    history = logger.get_session_history(session_id, limit=20)
    with st.sidebar:
        st.markdown("### Πρόσφατες ερωτήσεις")
        if not history:
            st.caption("Δεν υπάρχουν προηγούμενες ερωτήσεις.")
        else:
            for entry in history:
                label = f"{_short_ts(entry.timestamp)} — {_truncate(entry.query, 60)}"
                if st.button(label, key=f"hist_{entry.id}", use_container_width=True):
                    st.session_state.viewing_history_id = entry.id
                    st.session_state.pop("pending_query", None)
                    st.rerun()
        if history and st.button("Νέα ερώτηση", key="new_q", use_container_width=True):
            st.session_state.pop("viewing_history_id", None)
            st.session_state.pop("pending_query", None)
            st.rerun()

        st.divider()
        st.caption(f"Session: `{session_id[:8]}…`")
    return history


# ---------- pipeline execution ----------

def _run_query(query: str, session_id: str, top_k: int) -> None:
    """Stream the answer and render the full result + feedback widget."""
    pipeline = _get_pipeline()

    async def _start_stream():
        return await pipeline.ask_stream(
            query=query, session_id=session_id, top_k=top_k,
        )

    placeholder = st.empty()
    with st.spinner("Αναζήτηση και ανάλυση πηγών..."):
        token_iter = asyncio.run(_start_stream())

    def _wrapped_iter():
        yield from token_iter

    placeholder.write_stream(_wrapped_iter())

    response = pipeline.finalize_stream()
    placeholder.empty()
    _render_response_body(response)

    if response.query_id is not None:
        st.divider()
        st.caption("Πώς ήταν η απάντηση;")
        _render_feedback_widget(response.query_id, _get_query_logger())


# ---------- site password gate ----------

def check_site_password() -> bool:
    """Return True if authenticated for this session; render gate and return False otherwise."""
    if st.session_state.get("site_authenticated"):
        return True

    expected: str | None = None
    try:
        expected = st.secrets.get("SITE_PASSWORD")  # type: ignore[attr-defined]
    except Exception:
        pass
    expected = expected or os.getenv("SITE_PASSWORD") or None

    if not expected:
        st.error(
            "Site password δεν έχει ρυθμιστεί. "
            "Ορίστε SITE_PASSWORD στις μεταβλητές περιβάλλοντος ή στο .streamlit/secrets.toml."
        )
        st.stop()

    st.title("Domiki RAG")
    st.markdown("Εισάγετε τον κωδικό πρόσβασης για να συνεχίσετε.")
    # Use st.form so the submit button is always rendered alongside the input,
    # regardless of CookieManager reruns or Enter-key-triggered reruns.
    with st.form("site_password_form"):
        password = st.text_input(
            "Κωδικός",
            type="password",
            label_visibility="collapsed",
            placeholder="Κωδικός πρόσβασης",
        )
        submitted = st.form_submit_button("Είσοδος", type="primary")
    if submitted:
        if password == expected:
            st.session_state["site_authenticated"] = True
            st.rerun()
        else:
            st.error("Λάθος κωδικός.")
    return False


# ---------- main ----------

def main() -> None:
    st.set_page_config(
        page_title="Domiki RAG",
        page_icon="🏗",
        layout="wide",
    )
    if not check_site_password():
        return

    st.title("Domiki RAG — Βοηθός Πολεοδομικής Νομοθεσίας")
    st.caption(
        "Q&A πάνω σε ελληνική πολεοδομική και κατασκευαστική νομοθεσία, "
        "με αναφορές σε άρθρα και σελίδες."
    )
    st.warning(
        "Demo / personal use. Verify all answers with primary sources. "
        "Η εφαρμογή δεν αποτελεί νομική συμβουλή."
    )

    session_id = _ensure_session_id()
    logger = _get_query_logger()

    with st.sidebar:
        st.header("Ρυθμίσεις")
        top_k = st.slider("Πλήθος αποσπασμάτων (top-k)", 3, 15, 8)
        st.caption(
            "Πόσα αποσπάσματα στέλνονται στο LLM. "
            "Περισσότερα = περισσότερο context, μεγαλύτερο κόστος."
        )
        st.divider()

    history = _render_sidebar_history(session_id, logger)

    # --- routing: history view / pending query / welcome / input ---
    viewing_id = st.session_state.get("viewing_history_id")
    pending = st.session_state.pop("pending_query", None)

    if viewing_id is not None:
        entry = logger.get_by_id(viewing_id)
        if entry is None:
            st.error("Δεν βρέθηκε η ερώτηση.")
            st.session_state.pop("viewing_history_id", None)
        else:
            _render_cached_entry(entry, logger)
        return

    if pending:
        st.markdown(f"### {pending}")
        _run_query(pending, session_id=session_id, top_k=top_k)
        return

    # show welcome if no history, else input form
    if not history:
        _render_welcome("pending_query")
        if st.session_state.get("pending_query"):
            st.rerun()

    # Wrap in st.form so the submit button is available while typing
    # (no Ctrl+Enter needed, always enabled).
    with st.form("query_form", clear_on_submit=True):
        query = st.text_area(
            "Ερώτηση",
            placeholder="π.χ. Μπορώ να χτίσω πισίνα σε εκτός σχεδίου ακίνητο 2 στρ. με Σ.Δ. 0.4;",
            height=100,
        )
        submitted = st.form_submit_button("Υποβολή", type="primary")

    if submitted:
        q = query.strip()
        if not q:
            st.info("Γράψε μια ερώτηση πρώτα.")
        else:
            st.session_state.pending_query = q
            st.rerun()


main()
