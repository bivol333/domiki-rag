# Task: Fix the cookie-consent dismissal in download_laws.py (it's not working)

The consent dismissal in `scripts/download_laws.py` is NOT removing the popup — the test PDF still shows the e-nomothesia consent modal. The modal has buttons: **"Συναίνεση"** (accept), **"Δεν συγκατατίθεμαι"**, **"Διαχείριση επιλογών"**, and an **X** close button at top-right.

Likely causes: the dismiss ran before the modal finished loading (it appears after networkidle), and/or the modal is inside an iframe so a plain text-click didn't find it.

## Fix the consent handling — make it robust

### Best approach: persistent context + dismiss once
1. Launch Playwright with a **persistent browser context** (`launch_persistent_context` with a user-data dir like `data/.pw_profile`). This way, once we accept consent on the first page, the consent cookie persists and later pages won't show the popup at all.
2. On the FIRST page, after load, explicitly handle the consent (below). After that, subsequent pages should be clean — but still call the dismiss function on every page as a safety net (it should no-op if no modal).

### `dismiss_consent(page)` — robust version
Call this AFTER navigation + scroll-load and RIGHT BEFORE `page.pdf()`. Steps:

1. **Wait for the modal to appear** (it loads late): wait up to ~6s for any of these to be visible, but don't crash if none appear (page may already be consented):
   - a button/element with visible text "Συναίνεση"
   - or text "Δεν συγκατατίθεμαι"
   - or a consent container (class/id containing "consent"/"cookie"/"cmp"/"qc-cmp"/"gdpr")

2. **Check both the main page AND all iframes.** CMP modals are often in an iframe. Iterate `page.frames` and in each frame try to find and click the accept button. So the click logic must run against the page and every frame.

3. **Click "Συναίνεση"** (the accept button). Match by visible text "Συναίνεση" (exact or contains), case-insensitive. If not found, try the **X close button** (look for an element with aria-label/title containing "close"/"κλείσιμο" or a button containing "×"). 

4. **Wait for the modal to disappear** — wait until the "Συναίνεση" button/consent container is detached or hidden (up to ~5s).

5. **Fallback CSS/JS hide** (only if still present after clicking): inject JS that removes/hides any element that is `position: fixed` or `position: absolute` covering most of the viewport, plus any element whose class/id contains consent/cookie/cmp/modal/overlay/backdrop/gdpr, and reset `document.body.style.overflow = 'auto'`. Run this in the main frame AND iframes' parent containers.

6. After dismissal, wait ~1s for layout to settle before printing.

### Keep
- `--test` mode (single download of `YA-Ktiriodomikos-2023.pdf`), delete new/ PDFs first, headers/footers OFF, text-quality check, report, 60s timeout.

## After building

1. Delete new/ PDFs
2. Run `python scripts/download_laws.py --test`
3. Confirm the single PDF downloaded, and ideally verify programmatically that the consent text ("Ο εκδότης e-nomothesia.gr ζητά τη συναίνεση") does NOT appear in the extracted PDF text — report whether it's present or absent.

I'll then open the PDF to visually confirm the popup is gone before running the full batch.
