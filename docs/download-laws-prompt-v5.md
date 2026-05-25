# Task: Fix the 3 timeout downloads + add a retry-failed mode

The full batch downloaded 28/46 OK. 3 failures were TIMEOUTS (the page exists but `networkidle` never fires — these are large laws with long-polling/analytics that keep the network busy):
- N3852-2010-Kallikratis.pdf — https://www.e-nomothesia.gr/kat-demosia-dioikese/n-3852-2010.html
- N960-1979-Stathmefsi.pdf — https://www.e-nomothesia.gr/kat-metafores/n-960-1979.html
- N4070-2012-Keraies.pdf — https://www.e-nomothesia.gr/kat-epikoinonies/n-4070-2012.html

(The other 15 failures are HTTP 404 = wrong URLs; do NOT touch those — I'll fix the URLs in the manifest separately.)

## Changes to scripts/download_laws.py

### 1. Change the page-load wait strategy
Instead of waiting for `networkidle` (which can hang on pages with persistent connections), use `wait_until="domcontentloaded"` for `page.goto`, then explicitly wait for the legal content to be present (e.g. wait for the main article/content container, or wait a fixed 4–5s after domcontentloaded for late content + lazy-load), THEN do the scroll-to-load, THEN dismiss consent, THEN print. Keep the per-page timeout at 60s. This fixes the large-law timeouts without hanging on networkidle.

### 2. Add a `--retry-failed` mode
`python scripts/download_laws.py --retry-failed` should:
- Read the previous `data/raw_pdfs/download_report.txt` (or just re-process the manifest but SKIP any filename that already exists in `data/raw_pdfs/new/`)
- Simplest robust approach: process all `method=auto` rows, but SKIP rows whose output file already exists in `data/raw_pdfs/new/`. This way only the missing ones (the 3 timeouts + the 15 404s) are attempted; the 404s will just fail again harmlessly, and the 3 timeouts should now succeed with the new wait strategy.
- Do NOT delete existing new/ PDFs in this mode (we want to keep the 28 already downloaded).

### 3. Keep
Consent dismissal, fixed/sticky hide, headers/footers off, text-quality check, report (append or rewrite is fine), politeness delay.

## After building
Run `python scripts/download_laws.py --retry-failed` and show me the report. We expect the 3 timeout laws to now download (the 15 with 404 will still fail — that's expected, I'm fixing those URLs separately).
