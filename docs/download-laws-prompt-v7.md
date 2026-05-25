# Task: Fix 5 truncated law downloads + YA metadata law_number bug

Two fixes before the final rebuild.

## Fix 1 — 5 truncated laws (expand-all + better loading)

These 5 laws downloaded but are truncated (very few chunks) — the e-nomothesia pages load articles collapsed and/or are very large, so `domcontentloaded` + 5s didn't capture the full text:

| filename | url | chunks now |
|---|---|---|
| N1337-1983-Eisfores.pdf | https://www.e-nomothesia.gr/kat-periballon/skhedia-poleon/n-1337-1983.html | 3 |
| N3852-2010-Kallikratis.pdf | https://www.e-nomothesia.gr/kat-demosia-dioikese/n-3852-2010.html | 4 |
| N4070-2012-Keraies.pdf | https://www.e-nomothesia.gr/kat-epikoinonies/n-4070-2012.html | 5 |
| N4412-2016-DimosiesSymvaseis.pdf | https://www.e-nomothesia.gr/kat-demosia-erga/nomos-4412-2016.html | 4 |
| N960-1979-Stathmefsi.pdf | https://www.e-nomothesia.gr/kat-metafores/n-960-1979.html | 9 |

Enhance `scripts/download_laws.py` so that, before printing, it fully expands the law text:

1. **Click "expand all" if present.** e-nomothesia pages have a control to open all articles — look for a clickable element with visible text containing "Ανοίξτε τα όλα" / "Άνοιγμα όλων" / "Ανάπτυξη όλων" (case-insensitive). Click it and wait for content to expand (~3s). Check main page and iframes.

2. **More aggressive scroll-load:** scroll to bottom in multiple steps (e.g. 10 steps with 0.5s between), then wait for network to settle or a fixed 3s, to trigger any lazy-loaded article bodies. Repeat scroll once more after expand.

3. **Increase the post-load wait** for these large pages (e.g. up to 10s of total settle time before printing).

4. Keep consent-dismiss + fixed/sticky hide, headers/footers off, text-quality check.

Add a mode to re-download a **specific list** of filenames (e.g. `--only N1337-1983-Eisfores.pdf,N3852-2010-Kallikratis.pdf,...`) so we re-fetch ONLY these 5 into `data/raw_pdfs/public/` (overwrite the truncated ones in place — they were already moved to public/). After downloading, run the text-quality check and report char counts so we can confirm they're now full (expect tens of thousands of chars, not a few thousand).

## Fix 2 — YA/KYA metadata law_number bug

`YA-Ktiriodomikos-2023.pdf` got `law_number = 'Ν. 4495/2017'` (a body cross-reference) instead of its own identity. Its `source_type` is correctly `ministerial_decision`.

In `src/ingestion/metadata_extractor.py`: for filenames starting with `YA-` or `KYA-` (ministerial / joint-ministerial decisions), do NOT fall back to scanning the body for a law number (that grabs cross-references). Instead derive `law_number` from the filename's descriptive part — e.g. `YA-Ktiriodomikos-2023.pdf` → `law_number = "ΥΑ Κτιριοδομικός 2023"` (or a clean label from the filename tokens). The goal: ΥΑ/ΚΥΑ files must never inherit a referenced law's number. Add a test for `YA-Ktiriodomikos-2023.pdf` asserting law_number is NOT "Ν. 4495/2017" and source_type is "ministerial_decision".

## Order
1. Implement both fixes
2. Run tests
3. Re-download the 5 with the new expand-all logic (`--only ...`), report char counts
4. I'll then run the full `ingest.py --scope public --rebuild` + audit to confirm all 5 now have proper chunk counts and YA metadata is fixed, before migrating.

Report when the 5 re-downloads + tests are done. Do not run the full rebuild yourself.
