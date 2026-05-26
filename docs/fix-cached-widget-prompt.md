# Task: Fix "widget command in a cached function" error on login

After login, the live app throws this error (Streamlit):

> "Your script uses a widget command in a cached function (function decorated with @st.cache_data or @st.cache_resource). ... move all widget commands outside the cached function."

Traceback:
```
ui/streamlit_app.py line 403 main()
ui/streamlit_app.py line 346 in main → session_id = _ensure_session_id()
ui/streamlit_app.py line 78 in _ensure_session_id → cookies = _get_cookie_manager()
streamlit/runtime/caching/cache_utils.py ... (cached function widget error)
```

## Root cause
`_get_cookie_manager()` is decorated with `@st.cache_resource` (and/or `_get_query_logger()` is too), but `CookieManager` from `extra_streamlit_components` renders a **widget**. Streamlit forbids creating widgets inside `@st.cache_data`/`@st.cache_resource` functions — this breaks the app on load, likely corrupts `session_id` creation, and may be why query logging isn't working reliably.

## Fix
1. **Remove `@st.cache_resource`/`@st.cache_data` from `_get_cookie_manager()`.** Instantiate the `CookieManager` directly (it must be created in the normal script flow, not in a cached function). To keep a single instance per session and avoid duplicate-key errors, store it in `st.session_state` (e.g. create once: `if "cookie_manager" not in st.session_state: st.session_state.cookie_manager = stx.CookieManager(key="...")`), and give the CookieManager a stable unique `key`.

2. **Check `_get_query_logger()`** — if it's decorated with a cache decorator AND touches widgets or per-session state, fix similarly. If it only builds a DB-backed logger object (no widgets), `@st.cache_resource` is fine to keep; just confirm it doesn't create widgets.

3. Ensure `_ensure_session_id()` still works: it should get/set the session id cookie via the session-state-held CookieManager. Handle the first-render case where the cookie value may be `None` (don't crash — generate a new session id and set it).

4. Make sure this doesn't reintroduce the login-button issue (the form fix stays).

## Verify
- App loads after login with NO cached-widget error.
- `session_id` is created and stable across reruns.
- A query then logs correctly (this likely unblocks the Turso logging too).
- Existing tests pass.

## After
Report what you changed. I'll push and then verify: (a) no error on login, (b) a query appears in the Turso dashboard and survives a reboot.
