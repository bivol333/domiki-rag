# Task: Automated law PDF downloader from e-nomothesia.gr

Build a script that reads a manifest CSV and downloads each law as a PDF by rendering the e-nomothesia.gr page and printing it to PDF (replicating the manual browser "Print to PDF" the user currently does by hand).

## Input

A manifest file `laws_manifest.csv` (I will place it in the project root) with columns:
- `folder` — target subfolder: `new` (modern, monotonic Greek) or `old` (polytonic, scanned — needs OCR later)
- `filename` — exact output filename to save
- `url` — e-nomothesia.gr page URL (empty for manual_ocr rows)
- `method` — `auto` (download via this script) or `manual_ocr` (skip; just list as TODO)
- `note` — human description

## Output folders

- `data/raw_pdfs/new/` — modern laws (auto-downloaded)
- `data/raw_pdfs/old/` — polytonic/scanned laws (these are NOT auto-downloaded; they need scanned ΦΕΚ from et.gr + OCR — just create the folder and list them as TODO)

Create both folders if missing. Do NOT touch the existing `data/raw_pdfs/public/` folder.

## Script: `scripts/download_laws.py`

Requirements:

1. **Use Playwright (headless Chromium)** to render and print pages to PDF. This handles the lazy-loading JS content (the reason manual print sometimes truncates). Install note: the script should work after `pip install playwright --break-system-packages` and `playwright install chromium`. Detect if Playwright/Chromium is missing and print a clear install instruction instead of crashing.

2. **For each `method=auto` row:**
   - Open the URL in headless Chromium
   - Wait for `networkidle` (or a sensible timeout, e.g. 30s)
   - Scroll to the bottom of the page in steps to trigger lazy-loading of the full consolidated text, then wait ~2s
   - Print the page to PDF with `page.pdf()` using A4, print background, and **headers/footers disabled** (so we don't reintroduce the URL-footer noise we cleaned earlier)
   - Save to `data/raw_pdfs/{folder}/{filename}`
   - On HTTP error / navigation failure / timeout: record as FAILED with the reason, continue to next (never abort the whole run)

3. **Politeness / rate limiting:** wait 2–3 seconds between requests so we don't hammer e-nomothesia.

4. **Quality check after each download:** open the saved PDF with PyMuPDF (already a dependency) and count extractable text characters across the first 5 pages. Classify:
   - `OK` — substantial text (e.g. > 2000 chars)
   - `LOW_TEXT` — under 2000 chars (likely a scanned page, a login wall, or wrong/empty page — needs manual attention)
   - `EMPTY` — zero text
   Record the classification + char count per file.

5. **For each `method=manual_ocr` row:** do NOT download. Just add it to a TODO list in the report (filename + note), since these need scanned ΦΕΚ from et.gr + OCR (separate future step).

6. **Final report** printed to console AND written to `data/raw_pdfs/download_report.txt`:
   - SUCCEEDED (OK): count + list
   - LOW_TEXT / EMPTY (needs manual check): list with char counts and URLs — these are the ones where my best-guess URL may be wrong or the page is scanned/login-walled
   - FAILED (404/error): list with URLs and error reason
   - TODO (manual_ocr): list

   Make the report easy to act on: for LOW_TEXT/EMPTY/FAILED, print the URL so the user can open it manually and either fix the URL or print by hand.

## Important notes / caveats

- Several URLs in the manifest are best-guess (e-nomothesia path patterns). Expect some 404s — that's fine, just log them clearly so the user can correct them via the e-nomothesia search box.
- Do NOT log in. We rely on the publicly available consolidated text (which is full-text for modern laws). If a page only shows a scanned ΦΕΚ or a login wall, it will show up as LOW_TEXT/EMPTY in the report — that's the signal it needs the OCR path instead.
- Do NOT ingest anything. This script only downloads + reports. Ingestion is a separate step I run afterward.
- Keep it a single self-contained script. No changes to the existing pipeline.

## After building

Run it and show me the final report. Then I'll review which downloaded cleanly, manually fix any failed URLs, and we proceed to ingestion of the `new/` folder.
