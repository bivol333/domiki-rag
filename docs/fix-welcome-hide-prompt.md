# Task: Hide welcome intro + suggested questions during generation AND answer display

The collect-then-render answer fix works. But there's still a UI problem: while the answer is being generated (the "⏳ Σύνταξη απάντησης…" spinner is showing) AND/OR while an answer is displayed, the **welcome block still renders** — i.e. the intro text ("Αυτό είναι ένα βοηθητικό εργαλείο για ερωτήματα...") and the 3 suggested-question buttons appear below the spinner. They should NOT.

The previous guard in `_render_welcome` (early-return if `pending_query`/`viewing_history_id`) apparently doesn't cover the actual generation phase — investigate why. Likely the query runs synchronously in the same script run where the welcome is also rendered, or the welcome renders before the pending state is set, or the state key checked doesn't match the one set on submit.

## Desired behavior
- **Empty state only** (no question asked yet, no answer being generated, not viewing history): show the intro text + suggested-question buttons.
- **The moment a question is submitted, during generation (spinner), and while an answer is displayed**: do NOT render the intro text or the suggested-question buttons.
- The input form (Ερώτηση + Υποβολή) can stay available (so the user can ask another question) — that's fine. Only the intro text + suggestion buttons must hide.

## Fix
1. Trace the exact session_state and control flow when the user submits a question: what state is set, in what order are `_render_welcome` / the query-run / the answer-render called.
2. Ensure the welcome block (intro + suggestions) is gated on a condition that is true ONLY in the genuine empty state — i.e. it must be false during the submit→generate→render cycle. If the query runs synchronously in the same run as the form submit, set a clear flag (e.g. `is_answering`/`pending_query`) BEFORE rendering the welcome, and gate the welcome on it.
3. Make sure that after the answer is shown, going back to the empty state (new/reset) brings the suggestions back.

## Keep intact
Everything else from the last change (collect-then-render answer, softened banner, spacing, Turso logging, citations, feedback, login form, cookie manager).

## Verify
- Ask a question → during the spinner, NO intro text and NO suggestion buttons are visible.
- After the answer renders → still no intro/suggestions (just the answer + sources + the input form).
- Fresh load (no question) → intro + suggestions show normally.
Report what the actual cause was (why the earlier guard didn't catch the spinner phase).
