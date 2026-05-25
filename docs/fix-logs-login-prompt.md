# Task: Fix two production bugs — (1) query logs not persisting on Streamlit Cloud, (2) intermittent login button

## Bug 1 (CRITICAL): Query logs disappear in production

Symptom: queries made by users do NOT appear in the Admin view. They were definitely made.

Root cause (confirm, then fix): Streamlit Community Cloud has an **ephemeral filesystem**. The app writes query logs to a local SQLite file (`data/logs.db`). When the app restarts / redeploys / sleeps (which happens regularly on the free tier), that file is wiped — so all logged queries are lost. This works locally (file persists) but not in cloud.

### Step 1 — Confirm
Briefly verify the logging currently writes to a local SQLite path and the Admin reads from the same local file. Confirm there's no external/persistent store. Report what you find.

### Step 2 — Implement persistent logging via libSQL/Turso
Migrate query logging + feedback storage to a persistent external database that survives restarts. Use **libSQL (Turso)** because it is SQLite-compatible — minimal change from the current SQLite code.

Requirements:
- Add the `libsql-client` (or `libsql-experimental`) dependency.
- Read credentials from env/secrets: `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`.
- Create a small data-access layer so that:
  - If `TURSO_DATABASE_URL` is set → use libSQL (cloud, persistent) for reads/writes.
  - If NOT set (local dev) → fall back to the existing local SQLite `data/logs.db` (so local development is unchanged).
- Keep the SAME schema (queries table, feedback table, query_id linkage, timestamps, etc.) — just point it at the persistent backend.
- Ensure BOTH the logging path (writes) AND the Admin view (reads) use this data-access layer, so they read/write the same persistent store.
- Migrate the schema-creation (CREATE TABLE IF NOT EXISTS) to run against the libSQL DB on startup.
- Wrap DB operations in try/except so a logging failure never breaks the user-facing query flow (log the error, continue).

I will create a free Turso database and add `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` to Streamlit Cloud secrets (and my local env). Tell me the exact secret names you used so I set them correctly.

### Tests
- Test the data-access layer writes+reads a query log round-trip (can mock/skip network or use local sqlite fallback).
- Existing tests still pass.

## Bug 2: Intermittent "Είσοδος" (login) button unavailable

Symptom: on the site-password screen, the "Είσοδος" (login/submit) button is sometimes not available/clickable.

Investigate the auth/login flow in the Streamlit app (the site-password gate). Likely causes to check: a Streamlit rerun/state race, the button disabled until a state var is set, the cookie-manager component not yet mounted (extra-streamlit-components cookies often return None on first render), or the button being inside a conditional that hasn't rendered yet.

Fix so the login control is reliably available on every render:
- If it's a cookie-manager timing issue (cookies None on first run), handle the initial None state gracefully so the form/button always renders.
- Ensure the password input + submit button are always rendered together (e.g. use a stable `st.form` with a submit button) so the submit is never missing.
- Avoid relying on a value that may be None on first render to gate the button.

Report the root cause you find before/with the fix.

## Workflow
1. Confirm Bug 1 root cause + investigate Bug 2; report findings.
2. Implement both fixes.
3. Tell me the exact secret names for Turso so I can configure Streamlit Cloud + local.
4. Run tests.

Do not deploy — I'll set the secrets, then push and verify on Streamlit Cloud.
