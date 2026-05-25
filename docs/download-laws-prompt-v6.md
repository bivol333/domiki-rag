# Task: Auto-resolve failed URLs via e-nomothesia search (fix the 15 HTTP 404s)

15 laws failed with HTTP 404 because the manifest URLs use the wrong slug pattern. Newer laws on e-nomothesia use `nomos-XXXX-YYYY-phek-...` (not `n-XXXX-YYYY`), and category paths vary. Rather than hardcode exact URLs, make the script resolve the correct URL itself using e-nomothesia's site search.

## Enhancement to scripts/download_laws.py

### URL resolution fallback via search
When a manifest `url` returns HTTP 404 (or is empty for a row we still want to try), resolve the real URL by searching e-nomothesia:

1. **Derive a search query from the filename.** Parse the output filename into a law identifier:
   - `N4412-2016-...` → search `"4412/2016"`
   - `PD-59-2018-...` → search `"59/2018"` (or `"π.δ. 59/2018"`)
   - `YA-...` / `KYA-...` → use the descriptive note from the manifest as the query, or the number if present
   The manifest has a `note` column with a Greek description — use it as a secondary query if the number-based search returns nothing.

2. **Use e-nomothesia's search.** Navigate to the site search. Try the search URL form first (inspect the site — it's typically `https://www.e-nomothesia.gr/search.html?query=...` or similar; if unsure, load the homepage, fill the search input, submit). 

3. **Pick the correct result.** From the search results page, find the first result link whose text/URL contains the law number AND year (e.g. contains both "4412" and "2016"). Prefer links under `e-nomothesia.gr` that look like a law page (path contains `nomos-` or `n-` or `proedriko-diatagma-` or `-phek-`). Avoid "law-news" announcement pages.

4. **Navigate to that URL and download** as normal (consent dismiss, fixed/sticky hide, scroll, print to PDF, text check).

5. **Record the resolved URL** in the report so I can update the manifest permanently. Output a section "RESOLVED VIA SEARCH" listing filename → resolved URL.

### Known correction (apply directly)
For `N4759-2020-Xorotaxikos.pdf`, the correct URL is:
`https://www.e-nomothesia.gr/kat-periballon/nomos-4759-2020-phek-245a-9-12-2020.html`
Update the manifest row (or hardcode this one).

### Run mode
Use the existing `--retry-failed` behavior (skip files already present in `data/raw_pdfs/new/`), so only the missing ones are attempted. Keep the 31 already-downloaded PDFs untouched.

### Robustness
- If search resolution finds no good match for a row, mark it `UNRESOLVED` in the report (I'll handle those manually) — don't crash.
- Keep politeness delays. Don't hammer the search.

## After building
Run `python scripts/download_laws.py --retry-failed` and show me:
- How many of the 15 were resolved + downloaded OK
- The "RESOLVED VIA SEARCH" list (filename → URL) so I can update the manifest
- Any UNRESOLVED ones
