"""Streamlit UI for Domiki RAG."""
import asyncio
import re

import streamlit as st

from src.generation.answer_generator import AnswerGenerator
from src.generation.claude_client import ClaudeClient
from src.generation.models import AnswerResponse
from src.pipeline.qa_pipeline import QAPipeline
from src.retrieval.retriever import Retriever

_CITATION_RE = re.compile(r"\[Source:\s*((?:chunk_\d+\s*,?\s*)+)\]", re.IGNORECASE)
_CHUNK_NUM_RE = re.compile(r"chunk_(\d+)", re.IGNORECASE)


# Cohere embed-multilingual-v3.0: $0.10 / 1M tokens (input only)
# Claude Sonnet 4.6: $3 / 1M input tokens, $15 / 1M output tokens
def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0


@st.cache_resource
def _get_pipeline() -> QAPipeline:
    retriever = Retriever()
    generator = AnswerGenerator(ClaudeClient())
    return QAPipeline(retriever, generator)


def _replace_citations_for_display(text: str) -> str:
    """Replace [Source: chunk_N] markers with markdown superscripts like ⁽¹⁾."""
    def _to_super(match: re.Match) -> str:
        nums = [int(m.group(1)) for m in _CHUNK_NUM_RE.finditer(match.group(1))]
        if not nums:
            return ""
        joined = ",".join(str(n) for n in nums)
        return f"<sup>[{joined}]</sup>"
    return _CITATION_RE.sub(_to_super, text)


def _render_source_card(idx: int, hit) -> None:
    rh = hit
    h = rh.hit
    header_parts = [p for p in (h.law_number, h.article, h.paragraph) if p]
    header = " · ".join(header_parts) if header_parts else "(χωρίς μεταδεδομένα)"
    pages = (
        f"σελ. {h.page_start}-{h.page_end}"
        if h.page_start is not None and h.page_end is not None and h.page_end != h.page_start
        else (f"σελ. {h.page_start}" if h.page_start is not None else "")
    )
    st.markdown(f"**[{idx}]** {header}  ·  {pages}")
    st.caption(f"Αρχείο: {h.source_file or '—'}  ·  rerank_score: {rh.rerank_score:.3f}")
    text = h.text or ""
    if len(text) > 300:
        with st.expander("Πλήρες κείμενο αποσπάσματος"):
            st.text(text)
        st.text(text[:300] + "…")
    else:
        st.text(text)
    st.divider()


def _render_answer_section(response: AnswerResponse) -> None:
    if response.refused:
        st.warning("⚠ Το σύστημα αρνήθηκε να απαντήσει — οι διαθέσιμες πηγές δεν επαρκούν.")

    if response.has_invalid_citations:
        st.info(
            "Σημείωση: το μοντέλο αναφέρθηκε σε απόσπασμα που δεν παρασχέθηκε. "
            "Αυτές οι αναφορές έχουν αντικατασταθεί με «[αναφορά μη διαθέσιμη]»."
        )

    rendered = _replace_citations_for_display(response.answer_text)
    st.markdown(rendered, unsafe_allow_html=True)

    if response.source_chunks:
        with st.expander(f"Πηγές ({len(response.source_chunks)})", expanded=False):
            for i, hit in enumerate(response.source_chunks, 1):
                _render_source_card(i, hit)

    with st.expander("Λεπτομέρειες εκτέλεσης", expanded=False):
        timing = response.timing
        col1, col2, col3 = st.columns(3)
        col1.metric("Retrieval", f"{timing.get('retrieval_ms', 0):.0f} ms")
        col2.metric("Generation", f"{timing.get('generation_ms', 0):.0f} ms")
        col3.metric("Total", f"{timing.get('total_ms', 0):.0f} ms")

        in_tok = response.token_usage.get("input_tokens", 0)
        out_tok = response.token_usage.get("output_tokens", 0)
        cost = _estimate_cost_usd(in_tok, out_tok)
        st.caption(f"Tokens: in={in_tok}, out={out_tok}  ·  εκτίμηση κόστους: ${cost:.4f}")


def _run_query(query: str, top_k: int) -> None:
    pipeline = _get_pipeline()

    placeholder = st.empty()
    full_text_chunks: list[str] = []

    async def _start_stream():
        return await pipeline.ask_stream(query=query, top_k=top_k)

    with st.spinner("Αναζήτηση και ανάλυση πηγών..."):
        token_iter = asyncio.run(_start_stream())

    def _wrapped_iter():
        for delta in token_iter:
            full_text_chunks.append(delta)
            # Show streaming raw text (citations as-is); replaced after completion
            yield delta

    placeholder.write_stream(_wrapped_iter())

    # After streaming completes, replace placeholder with formatted final response
    response = pipeline.finalize_stream()
    placeholder.empty()
    _render_answer_section(response)


def main() -> None:
    st.set_page_config(
        page_title="Domiki RAG",
        page_icon="🏗",
        layout="wide",
    )

    st.title("Domiki RAG — Βοηθός Πολεοδομικής Νομοθεσίας")
    st.caption(
        "Q&A πάνω σε ελληνική πολεοδομική και κατασκευαστική νομοθεσία, "
        "με αναφορές σε άρθρα και σελίδες."
    )
    st.warning(
        "Demo / personal use. Verify all answers with primary sources. "
        "Η εφαρμογή δεν αποτελεί νομική συμβουλή."
    )

    with st.sidebar:
        st.header("Ρυθμίσεις")
        top_k = st.slider("Πλήθος αποσπασμάτων (top-k)", 3, 15, 8)
        st.caption(
            "Πόσα αποσπάσματα στέλνονται στο LLM. "
            "Περισσότερα = περισσότερο context, μεγαλύτερο κόστος."
        )

    query = st.text_area(
        "Ερώτηση",
        placeholder="π.χ. Μπορώ να χτίσω πισίνα σε εκτός σχεδίου ακίνητο 2 στρ. με Σ.Δ. 0.4;",
        height=100,
    )

    submitted = st.button("Υποβολή", type="primary", disabled=not query.strip())

    if submitted and query.strip():
        _run_query(query.strip(), top_k=top_k)


main()
