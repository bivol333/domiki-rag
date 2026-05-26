# Task: Change answer display from word-by-word streaming to paragraph-level reveal

Currently the generated answer streams token-by-token (word by word), which looks choppy. Change it so the answer appears **a full paragraph at a time** (each complete paragraph pops in whole, rendered as formatted markdown), which reads much more cleanly.

## Where
`ui/streamlit_app.py` — the part that displays the LLM answer (currently likely `st.write_stream(...)` over a token generator, or a manual loop updating `st.empty().markdown(...)` per token).

## Desired behavior (preferred: paragraph-buffered streaming)
Keep streaming under the hood (so we still get progress + don't block), but **buffer tokens and only update the visible output when a paragraph completes**:
- Accumulate streamed tokens into a buffer.
- A "paragraph boundary" = a double newline (`\n\n`). When the buffer contains one or more completed paragraphs, render all completed paragraphs (the accumulated full text so far) as markdown via a single `st.empty().markdown(accumulated_text)` update.
- Flush any remaining text at the end of the stream.
- Net effect: the reader sees whole paragraphs appear one after another, formatted, instead of words ticking in.

Render with `markdown` (not plain text) so headings, bold, lists, and the citation markers display formatted.

Show a spinner / "Σύνταξη απάντησης..." indicator while the first paragraph is still being generated, so there's immediate feedback.

## Alternative (if paragraph-buffering is awkward with the current pipeline)
If the streaming generator is hard to buffer cleanly, fall back to: show a spinner while generating the full answer, then render the complete formatted answer once with `st.markdown(...)`. (Simpler, clean, but no progressive reveal.) Use this only if buffering proves messy.

## Keep intact
- Citations rendering (the [1], [2]... references and the sources list) must still work.
- The query logging to Turso (log the final full answer, as now).
- The feedback widget.
- Don't reintroduce the form/button issues.

## Verify
- Ask a question on the app: the answer should appear paragraph-by-paragraph, formatted, not word-by-word.
- Citations + sources still render.
- The full answer is still logged.

Report which approach you used (paragraph-buffered vs full-at-once) and why.
