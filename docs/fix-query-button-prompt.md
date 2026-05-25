# Task: Fix the main query "Υποβολή" (submit) button — same issue as the login button

The login button was fixed with `st.form`, but the MAIN question-submission form on the home page has the same bug: while the user is typing in the "Ερώτηση" text area, the "Υποβολή" submit button is greyed-out / not clickable, and the input shows "Press Ctrl+Enter to apply". The user must Ctrl+Enter or click out before the button works — that's a bad UX and confuses users.

## Root cause
The question `st.text_area` and the "Υποβολή" `st.button` are NOT wrapped in a form (or the button has a `disabled=` condition tied to a session value that only updates after the input is committed). So mid-typing, the button is unavailable.

## Fix
In `streamlit_app.py` (the main query UI), wrap the question input + submit in a proper form:

- Use `st.form(...)` containing:
  - the `st.text_area("Ερώτηση", ...)`
  - a `st.form_submit_button("Υποβολή")`
- Remove any `disabled=...` condition on the submit button — it must always be clickable.
- On submit: read the text area's current value, strip it; if empty, show a gentle inline message ("Γράψε μια ερώτηση") and do nothing; otherwise run the query as before.
- Make sure the existing flow still works: streaming answer, citations, logging the query (now via Turso), feedback widget.

## Sample-question buttons
The two sample-question buttons at the top (e.g. "Ποιες κατασκευές μπορούν να υπαχθούν στον νόμο 4495/2017;") must still work — clicking one should populate/submit that question. If they currently set a session_state value and rerun, ensure that still triggers a query with the new form structure (e.g. set the pending question in session_state and process it on rerun, or submit the form programmatically). Verify both the sample buttons AND typing-then-Υποβολή both work.

## Also re-check the Admin login button
Confirm the Admin page (`1_Admin.py`) password submit is also a `st.form_submit_button` and always clickable (the previous fix should already cover it — just verify).

## Tests / verification
- Existing tests still pass.
- Describe how you verified the submit works on a single click while typing (no Ctrl+Enter needed) and that empty submit is handled.

Report the change. I'll push and test on Streamlit Cloud.
