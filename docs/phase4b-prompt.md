# Phase 4b: Site-Wide Password Gate

Read `CLAUDE.md` first. Phase 4a is complete with 134/134 tests passing, query logging, history, feedback, admin view.

## Goal of this phase

Before any user sees the main Streamlit app or any data, they must enter a site password. The password is configured via `SITE_PASSWORD` env var or Streamlit secrets. After successful entry, the user stays authenticated for the browser session (no re-entry on refresh until tab closed).

## Scope - keep minimal

- Just the password gate
- No user identification
- No rate limiting  
- No password recovery
- No multiple passwords
- No logout button (close tab = logout)

## Critical constraints

1. **The site password gate is INDEPENDENT from the admin password**. Even if a user enters the site password, they still need the `ADMIN_PASSWORD` to access `/Admin`. Both gates must remain functional.

2. **Don't break existing functionality**. All 134 tests must still pass.

3. **Don't break the user flow**. After auth, the existing welcome/sample questions screen should appear normally.

## Deliverables

```
ui/streamlit_app.py     # MODIFY: add check_site_password() function called at top of main()
.env.example            # MODIFY: add SITE_PASSWORD line with placeholder
tests/test_site_gate.py # NEW: tests for the gate
```

## Implementation specifications

### Add to `ui/streamlit_app.py`

A new function before main():

```python
def check_site_password() -> bool:
    """
    Returns True if user is authenticated (or already was), False otherwise.
    When False, renders the password prompt and stops further UI rendering.
    """
    # Already authenticated in this session?
    if st.session_state.get("site_authenticated"):
        return True
    
    # Resolve expected password: secrets first, then env var
    expected = None
    try:
        expected = st.secrets.get("SITE_PASSWORD")
    except Exception:
        pass
    expected = expected or os.getenv("SITE_PASSWORD")
    
    if not expected:
        st.error(
            "Site password δεν έχει ρυθμιστεί. "
            "Ορίστε SITE_PASSWORD στις μεταβλητές περιβάλλοντος ή στο .streamlit/secrets.toml."
        )
        st.stop()
    
    # Render gate UI
    st.title("Domiki RAG")
    st.markdown("Εισάγετε τον κωδικό πρόσβασης για να συνεχίσετε.")
    
    password = st.text_input(
        "Κωδικός",
        type="password",
        key="site_password_input",
        label_visibility="collapsed",
        placeholder="Κωδικός πρόσβασης",
    )
    
    if st.button("Είσοδος", type="primary"):
        if password == expected:
            st.session_state["site_authenticated"] = True
            st.rerun()
        else:
            st.error("Λάθος κωδικός.")
    
    return False
```

### Call from main()

```python
def main():
    if not check_site_password():
        return
    
    # ... all existing main() code
```

### Modify `.env.example`

Add a new line (keep existing content):

```
SITE_PASSWORD=change-me-for-beta
ADMIN_PASSWORD=different-from-site-password
```

If `ADMIN_PASSWORD` already exists, just ensure both are documented as separate values with a comment line above:

```
# Two independent passwords:
# SITE_PASSWORD - given to beta testers to access the app
# ADMIN_PASSWORD - private, only the developer, to access /Admin
SITE_PASSWORD=change-me-for-beta
ADMIN_PASSWORD=different-from-site-password
```

### Admin page check

Verify `ui/pages/1_Admin.py` still has its own independent `ADMIN_PASSWORD` gate. If the same `st.session_state["site_authenticated"]` accidentally also grants admin access, that's a bug. The two gates must be fully independent.

If needed, the admin page should use a separate session_state key like `admin_authenticated`.

### Tests `tests/test_site_gate.py`

Use `streamlit.testing.v1.AppTest` if available in your streamlit version (1.57+ has it), otherwise mock `st.session_state` and `os.environ`.

Test cases (at minimum):

1. **No SITE_PASSWORD env var** → gate shows configuration error
2. **Correct password entered** → sets `site_authenticated=True`, app proceeds
3. **Wrong password entered** → stays unauthenticated, shows error
4. **Already authenticated** → skips gate entirely, returns True immediately
5. **Empty password submitted** → stays unauthenticated, shows error
6. **site_authenticated is independent from admin_authenticated** → being site_authenticated does NOT grant admin access

If `AppTest` makes some of these awkward, prefer mocking and unit-testing `check_site_password()` directly.

## Acceptance criteria

Phase 4b is done when:

- [ ] All 134 existing tests still pass
- [ ] New site_gate tests pass (at least 6 covering above cases)
- [ ] `uv run ruff check src/ scripts/ tests/ ui/` clean
- [ ] **Manual test**: Setting `SITE_PASSWORD="test123"` and running `uv run streamlit run ui/streamlit_app.py`:
  - First load: shows password screen, not the main app
  - Wrong password: shows error, no main app
  - Correct password: main app appears (welcome screen with 3 sample questions)
  - Page refresh after auth: still authenticated, no re-entry needed
- [ ] **Admin independence verified**: Going to `/Admin` after site auth still requires the ADMIN_PASSWORD (no shortcut)
- [ ] Without `SITE_PASSWORD` env var set: app shows clear configuration error and won't render

## Out of scope - DO NOT DO

- Cookie-based persistent auth (use st.session_state - resets when tab closes, that's fine)
- Multiple/per-user passwords
- Password reset flow
- Rate limiting on password attempts
- User naming/identification
- Logout button
- Login analytics
- Adding new dependencies

## Implementation order

1. Add `check_site_password()` to `streamlit_app.py`
2. Call from `main()` top
3. Update `.env.example`
4. Verify admin page is independent (read its code, confirm separate session_state key)
5. Write tests
6. Run full test suite to confirm no regressions
7. Manual smoke test with SITE_PASSWORD set

Ask clarifying questions before coding if any spec point is ambiguous.
