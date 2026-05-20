"""Admin view: password-gated browser over the query log."""
import os
from datetime import datetime, timedelta

import streamlit as st

from src.observability.logger import QueryLogger

_PAGE_SIZE = 50


@st.cache_resource
def _get_query_logger() -> QueryLogger:
    return QueryLogger()


def _read_admin_password() -> str | None:
    """Resolve the admin password from st.secrets or env. Returns None if unset."""
    try:
        secret = st.secrets.get("ADMIN_PASSWORD")  # type: ignore[attr-defined]
    except (FileNotFoundError, KeyError, AttributeError):
        secret = None
    return secret or os.getenv("ADMIN_PASSWORD") or None


def _password_gate() -> bool:
    """Render the password form. Return True if authenticated."""
    expected = _read_admin_password()
    if expected is None:
        st.error(
            "ADMIN_PASSWORD δεν έχει οριστεί. Ορίστε το στο .streamlit/secrets.toml "
            "ή ως μεταβλητή περιβάλλοντος."
        )
        st.stop()

    if st.session_state.get("admin_authed"):
        return True

    st.subheader("Πρόσβαση Admin")
    entered = st.text_input("Admin password", type="password")
    if st.button("Είσοδος", type="primary"):
        if entered == expected:
            st.session_state.admin_authed = True
            st.rerun()
        else:
            st.error("Λάθος password")
    return False


def _date_range_for_choice(choice: str) -> tuple[datetime | None, datetime | None]:
    now = datetime.now()
    if choice == "Τελευταίες 24 ώρες":
        return now - timedelta(hours=24), None
    if choice == "Τελευταίες 7 ημέρες":
        return now - timedelta(days=7), None
    if choice == "Τελευταίες 30 ημέρες":
        return now - timedelta(days=30), None
    return None, None


def _feedback_filter_value(choice: str) -> str | None:
    mapping = {
        "Όλες": None,
        "Θετικό feedback": "positive",
        "Αρνητικό feedback": "negative",
        "Χωρίς feedback": "none",
    }
    return mapping.get(choice)


def _render_filters() -> dict:
    with st.sidebar:
        st.header("Φίλτρα")
        refused_only = st.checkbox("Μόνο refused")
        feedback_choice = st.radio(
            "Feedback",
            ["Όλες", "Θετικό feedback", "Αρνητικό feedback", "Χωρίς feedback"],
        )
        date_choice = st.radio(
            "Ημερομηνία",
            [
                "Όλες",
                "Τελευταίες 24 ώρες",
                "Τελευταίες 7 ημέρες",
                "Τελευταίες 30 ημέρες",
            ],
        )
        if st.button("Επαναφόρτωση", use_container_width=True):
            st.rerun()
        if st.button("Αποσύνδεση", use_container_width=True):
            st.session_state.pop("admin_authed", None)
            st.rerun()

    date_from, date_to = _date_range_for_choice(date_choice)
    return {
        "refused_only": refused_only,
        "feedback_filter": _feedback_filter_value(feedback_choice),
        "date_from": date_from,
        "date_to": date_to,
    }


def _render_query_card(entry) -> None:
    refused_flag = " 🚫 refused" if entry.refused else ""
    feedback_flag = ""
    if entry.feedback == "positive":
        feedback_flag = " 👍"
    elif entry.feedback == "negative":
        feedback_flag = " 👎"

    label = (
        f"#{entry.id} · {entry.timestamp.strftime('%Y-%m-%d %H:%M')}"
        f"{refused_flag}{feedback_flag}  ·  "
        f"{entry.query[:100]}{'…' if len(entry.query) > 100 else ''}"
    )
    with st.expander(label, expanded=False):
        st.caption(f"session_id: `{entry.session_id}`")
        st.markdown("**Ερώτηση:**")
        st.write(entry.query)
        st.markdown("**Απάντηση:**")
        st.text(entry.answer)

        if entry.chunks_used:
            st.markdown(f"**Χρησιμοποιημένα αποσπάσματα ({len(entry.chunks_used)}):**")
            for i, c in enumerate(entry.chunks_used, 1):
                parts = [
                    p for p in (c.get("law_number"), c.get("article"), c.get("paragraph"))
                    if p
                ]
                header = " · ".join(parts) if parts else "(χωρίς μεταδεδομένα)"
                ps, pe = c.get("page_start"), c.get("page_end")
                pages = ""
                if ps is not None and pe is not None:
                    pages = f" · σελ. {ps}-{pe}" if pe != ps else f" · σελ. {ps}"
                st.caption(
                    f"[{i}] {header}{pages}  ·  chunk_id: {c.get('chunk_id', '—')}"
                )

        if entry.feedback:
            st.markdown("**Feedback:**")
            label = "👍 positive" if entry.feedback == "positive" else "👎 negative"
            st.write(label)
            if entry.feedback_comment:
                st.write(f"_Σχόλιο:_ {entry.feedback_comment}")


def _render_pagination(total: int, page: int) -> None:
    n_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Προηγούμενο", disabled=page <= 1):
            st.session_state.admin_page = page - 1
            st.rerun()
    with col2:
        st.markdown(
            f"<div style='text-align:center'>Σελίδα {page} από {n_pages}  ·  {total} σύνολο</div>",
            unsafe_allow_html=True,
        )
    with col3:
        if st.button("Επόμενο →", disabled=page >= n_pages):
            st.session_state.admin_page = page + 1
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Domiki RAG · Admin", page_icon="🛠", layout="wide")
    st.title("Admin")

    if not _password_gate():
        return

    logger = _get_query_logger()
    filters = _render_filters()

    total = logger.count_total(**filters)
    page = st.session_state.get("admin_page", 1)
    page = max(1, min(page, max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)))
    st.session_state.admin_page = page

    rows = logger.get_all_queries(
        limit=_PAGE_SIZE,
        offset=(page - 1) * _PAGE_SIZE,
        **filters,
    )

    if not rows:
        st.info("Δεν βρέθηκαν εγγραφές με αυτά τα φίλτρα.")
        return

    for entry in rows:
        _render_query_card(entry)

    st.divider()
    _render_pagination(total, page)


main()
