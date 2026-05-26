# Task: Frontend refresh — fix answer rendering, hide sample questions while answering, polish

Run this with Opus 4.7. Three issues on the live app.

## Issue 1 (priority): Answer still renders word-by-word

The previous paragraph-buffering attempt did NOT work — the answer still appears 2–3 words at a time (choppy). Stop trying to buffer the stream; switch to the **reliable approach**:

- While generating, show a spinner with "⏳ Σύνταξη απάντησης…" (and keep retrieval feedback if present).
- **Do NOT stream tokens to the UI.** Collect the full answer text from the model, THEN render the complete answer **once** as formatted markdown via a single `st.markdown(...)`.
- This guarantees the user sees the whole, formatted answer appear at once (no word-by-word), like a finished document.
- Keep citations rendering (the `[1]`, `[2]`… markers → superscripts and the sources list), Turso logging of the final answer, and the feedback widget — all on the same finalize path as now.
- If a streaming generator is used internally for the API call, that's fine — just accumulate it fully before displaying; don't push partial text to the placeholder.

Investigate why the current buffered approach leaks partial text (e.g. `st.write_stream` being used, or the placeholder being updated per-chunk) and replace it with the collect-then-render approach.

## Issue 2: Sample/suggested questions stay visible while answering

The app shows suggested example questions (e.g. "Ποιες κατασκευές μπορούν να υπαχθούν στον νόμο 4495/2017;"). These should only appear on the **initial empty state**. Once the user submits a question (or an answer is being shown), **hide the suggested-question buttons** so they don't clutter the answer view. Show them again only when there's no active question/answer (e.g. fresh load or after a reset).

## Issue 3: General polish
- Consistent vertical spacing between the question, answer, and sources (no cramped or excessively large gaps).
- The "⚠ Το σύστημα αρνήθηκε να απαντήσει" banner currently appears even when the model then gives a useful partial answer — that's contradictory. Either (a) only show the refusal banner when the answer is a true refusal with no substantive content, or (b) soften it to something like "ℹ️ Μερική απάντηση — οι διαθέσιμες πηγές δεν καλύπτουν πλήρως το ερώτημα." Pick the cleaner option and apply consistently.
- Make sure the answer area, citations, and sources read cleanly as a finished response.

## Keep intact
- Login flow + the st.form fixes (don't reintroduce button issues).
- Turso logging, citations, feedback, session handling, cookie manager in session_state.
- No retrieval/ingestion/generation-prompt changes — this is frontend only.

## Verify
- A query shows a spinner, then the full formatted answer appears at once (not word-by-word).
- Suggested questions disappear once a question is asked.
- Refusal banner is consistent with the actual answer.
- Existing tests pass.

Report what was causing the word-by-word leak and what you changed.
