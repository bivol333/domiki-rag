# Task: Update download_laws.py — dismiss cookie-consent popup + test mode

The existing `scripts/download_laws.py` works (28 PDFs downloaded with good text), BUT e-nomothesia.gr shows a **cookie-consent modal popup** that overlays the page. It adds consent text as noise and visually covers the first page. We need to dismiss it before printing to PDF.

## Changes needed

### 1. Dismiss the cookie-consent popup before printing
After navigating to each page and before printing to PDF, dismiss the e-nomothesia cookie/consent modal. Use a robust multi-step approach (try each, don't fail if one doesn't apply):

a) **Click an accept button** — look for buttons/links by visible text matching (case-insensitive): "Αποδοχή", "Αποδοχή όλων", "Συμφωνώ", "Συναίνεση", "ΟΚ", "Accept". Click the first one found. Wait ~1s after clicking.

b) **Fallback — hide via JS/CSS injection:** after the click attempt, inject CSS/JS to remove any residual consent UI and page-blocking overlays. Hide elements that are fixed/absolute full-screen overlays or known consent containers (e.g. elements with class/id containing: "consent", "cookie", "cmp", "modal", "overlay", "backdrop", "gdpr"). Set `display:none` on them and restore `body { overflow: auto }` so nothing is blocked/scrolled-locked.

c) Verify the popup is gone (optional: check the consent text is no longer the topmost visible element) before printing.

Make this a reusable function `dismiss_consent(page)` called right after page load + scroll, before `page.pdf()`.

### 2. Delete existing PDFs in the new folder first
At the start of the run, delete all `*.pdf` files in `data/raw_pdfs/new/` (they were captured with the popup overlay). Do NOT touch `data/raw_pdfs/old/` or `data/raw_pdfs/public/`. Print what was deleted.

### 3. Add a `--test` mode
- `python scripts/download_laws.py --test` → process ONLY the first `method=auto` row whose URL previously succeeded (use `YA-Ktiriodomikos-2023.pdf` — its URL is confirmed working). Download just that ONE PDF to `data/raw_pdfs/new/`, run the text-quality check, and report. This lets the user open and visually verify the cookie popup is gone and the text is clean before we run the full batch.
- `python scripts/download_laws.py` (no flag) → full run of all `method=auto` rows (unchanged behavior, now with consent dismissal).

### 4. Keep everything else
- Headers/footers OFF, scroll-to-load, networkidle wait, 2–3s politeness delay, PyMuPDF text-quality check, the console + `download_report.txt` report (succeeded / low-text / failed / TODO).
- For the timeout cases (N1337, N3852, N4070), bump the per-page timeout to 60s.

## After building

1. Delete the new/ PDFs
2. Run `python scripts/download_laws.py --test`
3. Show me the result and confirm the single PDF (`YA-Ktiriodomikos-2023.pdf`) is in `data/raw_pdfs/new/`

I (the user) will then open that one PDF to verify the cookie popup is gone and the text is clean. Once I confirm, I'll run the full batch myself.
