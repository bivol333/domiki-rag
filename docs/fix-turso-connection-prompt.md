# Task: Turso logging is silently failing — app falls back to ephemeral SQLite

## Symptom
- `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` ARE set in Streamlit Cloud secrets (confirmed).
- BUT the Turso database is completely empty — no `queries` table, no rows.
- A query showed in /Admin BEFORE an app reboot, then was GONE after reboot.

Conclusion: the app is NOT actually using Turso. It silently falls back to the ephemeral local SQLite (which shows data until the container restarts, then loses it). The Turso backend is either not being selected, or its connection/init is throwing and being swallowed.

## Investigate + report
1. **How is the Turso URL read?** Check `src/observability/database.py`. Is it `os.getenv("TURSO_DATABASE_URL")`? On Streamlit Cloud, confirm whether secrets are visible via `os.getenv` — if not reliably, also read via `st.secrets`. Implement: read from `os.getenv(...)` and, if None, fall back to `st.secrets.get(...)` (guard the st import so non-Streamlit contexts/tests still work).

2. **URL scheme.** Turso gives a `libsql://<db>.turso.io` URL. The `_TursoLogDb` uses the HTTP `/v2/pipeline` API, which needs an **`https://`** base URL, not `libsql://`. Check how the endpoint is built. If it uses the raw `libsql://` URL with an HTTP client, that's the bug. Fix: normalize the URL — replace a leading `libsql://` with `https://` before calling the pipeline endpoint (`https://<db>.turso.io/v2/pipeline`).

3. **Surface errors at startup.** Right now DB errors are caught so they don't break the query flow — good for runtime, BAD for diagnosis because the Turso init failure is invisible. Add clear logging:
   - On startup / first use: log which backend was selected ("Using Turso backend: <https-url>" vs "Using local SQLite fallback (no TURSO_DATABASE_URL found)").
   - If a Turso request fails, log the status code + response body once (not just swallow).
   These logs appear in Streamlit Cloud's app logs so we can see exactly what's happening.

4. **Schema creation on Turso.** Ensure `CREATE TABLE IF NOT EXISTS queries ...` (and feedback) actually runs against Turso on init, and that a failure here is logged loudly.

## Fixes to implement
- Read secret via os.getenv → fallback st.secrets.
- Normalize `libsql://` → `https://` for the HTTP pipeline endpoint.
- Verify the auth header is `Authorization: Bearer <TURSO_AUTH_TOKEN>`.
- Add the backend-selection + error logging described above.
- Keep the SQLite fallback for local dev (no TURSO_DATABASE_URL).

## Verify
- Add/adjust a test for the URL normalization (libsql:// → https://) and for secret resolution (os.getenv then st.secrets).
- Existing tests pass.

## After
Tell me what you found (which of the causes applied). I'll push, then check the Streamlit Cloud app logs to confirm it now says "Using Turso backend", make a query, and verify it survives a reboot + appears in the Turso dashboard.
