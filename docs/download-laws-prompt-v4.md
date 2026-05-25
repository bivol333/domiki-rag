# Task: Identify + remove the residual element appearing on every PDF page

Good news: the consent popup is now dismissed. New issue: a white box (black bar with a chevron "˅" + light-blue bars) appears at the same spot on EVERY page of the printed PDF. This is almost certainly a `position: fixed` or `position: sticky` element (site header/toolbar or consent-bar residue) — in Chromium's print-to-PDF, fixed elements repeat on every page.

## Step 1 — Diagnose (so we see what it is)

Add a diagnostic that runs after consent dismissal and before printing, on the test page. It should collect and print (to console + report) all elements whose computed `position` is `fixed` or `sticky`, plus any element with a high z-index that spans most of the viewport width. For each, report:
- tag, id, class
- computed position, z-index
- bounding box (x, y, width, height)
- a short snippet of innerText (first 80 chars)

Run this for `YA-Ktiriodomikos-2023.pdf`'s page and show me the list, so we can identify the white box (its class/id).

## Step 2 — Remove it before printing

Add to the pre-print cleanup an injection that hides page chrome that would otherwise repeat on every printed page:
- Set `display: none` on ALL elements with computed `position: fixed` or `position: sticky`.
- Also re-run the consent/overlay hide (class/id containing consent/cookie/cmp/overlay/backdrop/gdpr).
- This is safe: legal body text is in normal static flow, not fixed/sticky, so we won't hide content.

Do this for the main page and any iframes. Then wait ~0.5s and print.

Optionally, also add a print CSS via `page.add_style_tag` / the `page.pdf` media: inject `@media print { [style*="position: fixed"], [style*="position:fixed"] { display:none !important } }` plus a rule hiding common fixed headers — but the JS computed-style approach above is the reliable one.

## Step 3 — Re-test

1. Delete new/ PDFs
2. Run `python scripts/download_laws.py --test`
3. Print the Step-1 diagnostic list (what fixed/sticky elements existed)
4. Confirm the residual box is gone (the diagnostic should now show none, or they're hidden)

Show me the diagnostic list + confirm. I'll open the PDF to verify it's clean (just the legal text, no white box on each page). Once confirmed, I run the full batch.
