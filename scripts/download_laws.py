"""
Download Greek legislation PDFs from e-nomothesia.gr using headless Chromium.
Reads laws_manifest.csv, downloads auto rows, reports all results.

Usage:
  uv run python scripts/download_laws.py          # full run
  uv run python scripts/download_laws.py --test   # single test URL only
"""
import argparse
import csv
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "laws_manifest.csv"
OUTPUT_BASE = PROJECT_ROOT / "data" / "raw_pdfs"
REPORT_PATH = OUTPUT_BASE / "download_report.txt"
# Persistent browser profile — once consent is accepted it sticks via cookies
PW_PROFILE_DIR = PROJECT_ROOT / "data" / ".pw_profile"

TEXT_THRESHOLD = 2000
PAGES_TO_CHECK = 5
PAGE_TIMEOUT = 60_000  # ms — bumped for large laws (N1337, N3852, N4070)

# Confirmed-working URL for --test mode
TEST_FILENAME = "YA-Ktiriodomikos-2023.pdf"

# Substring that appears in the consent modal text — used for programmatic check
CONSENT_PROBE_TEXT = "e-nomothesia.gr"

# JS: hide ALL fixed/sticky elements (nav bars, ads, consent residue) so they
# don't repeat on every printed page. Legal body text is in normal flow — safe.
_HIDE_FIXED_STICKY_JS = """
(function() {
    document.querySelectorAll("*").forEach(function(el) {
        var st = window.getComputedStyle(el);
        if (st.position === "fixed" || st.position === "sticky") {
            el.style.setProperty("display", "none", "important");
        }
    });
    document.body.style.overflow = "auto";
    document.documentElement.style.overflow = "auto";
})();
"""

# JS: also hide by consent/cookie/overlay class keywords (belt-and-suspenders)
_HIDE_CONSENT_JS = """
(function() {
    var keywords = ["consent","cookie","cmp","qc-cmp","fc-","gdpr","modal",
                    "overlay","backdrop","popup","banner"];
    var sel = keywords.flatMap(function(k) {
        return ['[id*="'+k+'"]','[class*="'+k+'"]'];
    }).join(",");
    document.querySelectorAll(sel).forEach(function(el) {
        el.style.setProperty("display","none","important");
    });
})();
"""

# JS: collect all fixed/sticky elements for diagnostic reporting
_DIAG_FIXED_JS = r"""
() => {
    const results = [];
    const vw = window.innerWidth, vh = window.innerHeight;
    document.querySelectorAll('*').forEach(el => {
        const st  = window.getComputedStyle(el);
        const pos = st.position;
        const zi  = parseInt(st.zIndex) || 0;
        const r   = el.getBoundingClientRect();
        const isFixedSticky = (pos === 'fixed' || pos === 'sticky');
        const isHighZ = zi > 50 && r.width > vw * 0.4;
        if (isFixedSticky || isHighZ) {
            results.push({
                tag:      el.tagName,
                id:       el.id || '',
                cls:      (typeof el.className === 'string')
                              ? el.className.slice(0, 120) : '',
                position: pos,
                zIndex:   st.zIndex,
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
                text: (el.innerText || '').replace(/\s+/g,' ').slice(0, 80),
            });
        }
    });
    return results;
}
"""

# ---------------------------------------------------------------------------
# URL resolution helpers — fix HTTP-404 manifest URLs via site search
# ---------------------------------------------------------------------------

# Hardcoded corrections for known wrong slugs (applied before search fallback)
KNOWN_URL_CORRECTIONS: dict[str, str] = {
    "N4759-2020-Xorotaxikos.pdf": (
        "https://www.e-nomothesia.gr/kat-periballon/"
        "nomos-4759-2020-phek-245a-9-12-2020.html"
    ),
}

def _parse_number_year(filename: str) -> tuple[str, str]:
    """
    Extract (number, year) from a PDF filename.
    e.g. "N4412-2016-DimosiesSymvaseis.pdf" → ("4412", "2016")
         "PD-59-2018-XriseisGis.pdf"        → ("59",   "2018")
         "KYA-29407-2002-..."               → ("29407","2002")
    Returns ("", "") if not parseable.
    """
    stem = Path(filename).stem
    for pattern in (
        r"^N(\d+)-(\d{4})-",           # N4412-2016-...
        r"^(?:PD|KYA|YA)-(\d+)-(\d{4})-",  # PD-59-2018, KYA-29407-2002, YA-...-YYYY
    ):
        m = re.match(pattern, stem, re.I)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def _slug_variations(base_path: str, number: str, year: str) -> list[str]:
    """
    Return candidate URLs by substituting common e-nomothesia slug patterns
    while keeping the same category directory (base_path = URL up to last /).
    Covers the main transition: old n-XXXX-YYYY → new nomos-XXXX-YYYY slugs
    and the decree variants.
    """
    if not number or not year:
        return []
    return [
        f"{base_path}/nomos-{number}-{year}.html",
        f"{base_path}/n-{number}-{year}.html",
        f"{base_path}/proedriko-diatagma-{number}-{year}.html",
        f"{base_path}/pd-{number}-{year}.html",
        f"{base_path}/kya-{number}-{year}.html",
        f"{base_path}/ya-{number}-{year}.html",
        f"{base_path}/koine-upourgike-apophase-{number}-{year}.html",
    ]


def resolve_url_via_search(page, filename: str, note: str, manifest_url: str = "") -> str | None:
    """
    Attempt to find the correct e-nomothesia page URL for a 404 manifest entry.

    Strategy (in order):
    1. Try slug variations on the same category directory as the manifest URL
       (handles n-XXXX → nomos-XXXX transitions and decree prefix variants).
    2. Browse the category listing page (1–2 pages) and look for a link whose
       href contains the law number (catches YA/KYA with complex slugs).

    Returns the first 200-OK URL found, or None (→ mark UNRESOLVED).
    """
    number, year = _parse_number_year(filename)
    base_path = manifest_url.rsplit("/", 1)[0] if manifest_url else ""

    # --- Strategy 1: slug variations ---
    for candidate in _slug_variations(base_path, number, year):
        if candidate.rstrip("/") == manifest_url.rstrip("/"):
            continue  # skip the manifest URL — already got 404
        try:
            resp = page.goto(candidate, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            if resp and resp.status == 200:
                return candidate
        except Exception:
            pass

    # --- Strategy 2: browse category listing for number in href ---
    if base_path and number:
        cat_url = base_path.rstrip("/") + "/"
        for pg in range(1, 3):  # first 2 listing pages
            listing = cat_url if pg == 1 else f"{cat_url}page/{pg}/"
            try:
                resp = page.goto(listing, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                if resp is None or resp.status >= 400:
                    break
                time.sleep(1.5)
                links: list[str] = page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.includes('e-nomothesia.gr') && h.endsWith('.html'))
                """)
                for lnk in links:
                    if number in lnk and (not year or year in lnk):
                        return lnk
            except Exception:
                break

    return None


# Accept-button labels to look for (case-insensitive contains match, Greek first)
_ACCEPT_LABELS = [
    "συναίνεση", "αποδοχή όλων", "αποδοχή", "αποδέχομαι", "συμφωνώ",
    "accept all", "accept", "ok",
]
# Close-button fallbacks
_CLOSE_LABELS = ["κλείσιμο", "close", "×", "✕", "✗"]

# Labels for the e-nomothesia "expand all articles" control
_EXPAND_ALL_LABELS = [
    "ανοίξτε τα όλα", "άνοιγμα όλων", "ανάπτυξη όλων",
    "expand all", "open all",
]


@dataclass
class DownloadResult:
    filename: str
    url: str
    note: str
    status: str  # OK | LOW_TEXT | EMPTY | FAILED | TODO
    char_count: int = 0
    error: str = ""
    resolved_url: str = ""  # set when a 404 was fixed via site search


@dataclass
class ManifestRow:
    folder: str
    filename: str
    url: str
    method: str
    note: str


def load_manifest() -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(ManifestRow(
                folder=row["folder"].strip(),
                filename=row["filename"].strip(),
                url=row["url"].strip(),
                method=row["method"].strip(),
                note=row["note"].strip(),
            ))
    return rows


def ensure_dirs(rows: list[ManifestRow]) -> None:
    folders = {r.folder for r in rows}
    for folder in folders:
        (OUTPUT_BASE / folder).mkdir(parents=True, exist_ok=True)


def purge_new_pdfs() -> None:
    """Delete all *.pdf files in data/raw_pdfs/new/."""
    new_dir = OUTPUT_BASE / "new"
    if not new_dir.exists():
        return
    deleted = list(new_dir.glob("*.pdf"))
    for f in deleted:
        f.unlink()
    if deleted:
        print(f"Deleted {len(deleted)} existing PDF(s) from data/raw_pdfs/new/:")
        for f in deleted:
            print(f"  - {f.name}")
    else:
        print("No existing PDFs in data/raw_pdfs/new/ to delete.")
    print()


def count_text_chars(pdf_path: Path) -> int:
    try:
        doc = fitz.open(str(pdf_path))
        total = 0
        for page in doc[:PAGES_TO_CHECK]:
            total += len(page.get_text())
        doc.close()
        return total
    except Exception:
        return 0


def extract_all_text(pdf_path: Path) -> str:
    """Return full text of all pages (for consent-probe check)."""
    try:
        doc = fitz.open(str(pdf_path))
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts)
    except Exception:
        return ""


def classify(char_count: int) -> str:
    if char_count == 0:
        return "EMPTY"
    if char_count < TEXT_THRESHOLD:
        return "LOW_TEXT"
    return "OK"


def check_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _try_click_in_frame(frame, accept_labels: list[str], close_labels: list[str]) -> bool:
    """Try to find and click an accept/close button in a single frame. Returns True if clicked."""
    try:
        candidates = frame.query_selector_all(
            "button, a[role=button], input[type=button], input[type=submit], [role=button]"
        )
    except Exception:
        return False

    # Prefer accept labels, then close labels
    for labels in (accept_labels, close_labels):
        for el in candidates:
            try:
                label = (el.inner_text() or "").strip().lower()
            except Exception:
                try:
                    label = (el.get_attribute("aria-label") or "").lower()
                except Exception:
                    label = ""
            for pattern in labels:
                if pattern in label:
                    try:
                        el.click()
                        return True
                    except Exception:
                        pass
    return False


def diagnose_fixed_sticky(page) -> list[dict]:
    """Return list of fixed/sticky elements found on the page (for --test reporting)."""
    try:
        return page.evaluate(_DIAG_FIXED_JS)
    except Exception:
        return []


def expand_articles(page) -> bool:
    """
    Click the 'expand all articles' button if present on e-nomothesia pages.
    Article bodies are collapsed by default; clicking this reveals full text.
    Returns True if a button was found and clicked.
    """
    all_frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for frame in all_frames:
        try:
            candidates = frame.query_selector_all(
                "button, a, span, div[role='button'], [onclick], [class*='expand'], [class*='open']"
            )
        except Exception:
            continue
        for el in candidates:
            try:
                label = (el.inner_text() or "").strip().lower()
            except Exception:
                continue
            for pat in _EXPAND_ALL_LABELS:
                if pat in label:
                    try:
                        el.click()
                        return True
                    except Exception:
                        pass
    return False


def dismiss_consent(page) -> None:
    """
    Robustly dismiss the e-nomothesia cookie/consent modal.

    Strategy:
    1. Wait up to 6s for the modal to appear (it loads after networkidle).
    2. Check the main frame AND every iframe for the accept button.
    3. Click "Συναίνεση" (or close button as fallback).
    4. Wait up to 5s for the modal to disappear.
    5. Fallback: JS/CSS injection to hide any residual overlay + ALL fixed/sticky.
    6. Wait 0.5s for layout to settle.
    """
    # Step 1: wait for modal to appear (any of several signals)
    modal_appeared = False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            for text in ("Συναίνεση", "Δεν συγκατατίθεμαι"):
                if page.locator(f"text={text}").count() > 0:
                    modal_appeared = True
                    break
            if not modal_appeared:
                for frame in page.frames[1:]:
                    for text in ("Συναίνεση", "Δεν συγκατατίθεμαι"):
                        try:
                            if frame.locator(f"text={text}").count() > 0:
                                modal_appeared = True
                                break
                        except Exception:
                            pass
                    if modal_appeared:
                        break
        except Exception:
            pass
        if modal_appeared:
            break
        time.sleep(0.3)

    # Step 2+3: try clicking in main frame, then every iframe
    clicked = False
    all_frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for frame in all_frames:
        if _try_click_in_frame(frame, _ACCEPT_LABELS, _CLOSE_LABELS):
            clicked = True
            break

    # Step 4: wait for modal to disappear (up to 5s)
    if clicked:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                still_visible = any(
                    page.locator(f"text={t}").count() > 0
                    for t in ("Συναίνεση", "Δεν συγκατατίθεμαι")
                )
                if not still_visible:
                    break
            except Exception:
                break
            time.sleep(0.2)

    # Step 5: hide ALL fixed/sticky elements (nav bar, ads, any consent residue)
    # This is the main fix for the repeating-header-on-every-page problem.
    for frame in all_frames:
        try:
            frame.evaluate(_HIDE_FIXED_STICKY_JS)
        except Exception:
            pass
        try:
            frame.evaluate(_HIDE_CONSENT_JS)
        except Exception:
            pass

    # Step 6: settle before printing
    time.sleep(0.5)


def download_one(page, row: ManifestRow, dest: Path, test_mode: bool = False) -> DownloadResult:
    try:
        # Determine the URL to try: known correction > manifest URL
        effective_url = KNOWN_URL_CORRECTIONS.get(row.filename, row.url)
        resolved_via_search = ""

        # Use domcontentloaded instead of networkidle: large laws (Kallikratis, N4070)
        # have persistent analytics connections that keep networkidle from ever firing.
        # After domcontentloaded we wait 5s for late JS/lazy content, then scroll.
        response = page.goto(effective_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        # --- URL-resolution fallback: try site search on 404 ---
        if response is None or response.status >= 400:
            if response is not None and response.status == 404:
                resolved = resolve_url_via_search(page, row.filename, row.note, manifest_url=row.url)
                if resolved:
                    resolved_via_search = resolved
                    response = page.goto(resolved, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

            # Still failed after resolution attempt
            if response is None or response.status >= 400:
                status_code = response.status if response else "no response"
                error_detail = "unresolved" if not resolved_via_search else f"resolved URL also {status_code}"
                return DownloadResult(
                    filename=row.filename,
                    url=effective_url,
                    note=row.note,
                    status="FAILED",
                    error=f"HTTP {status_code} ({error_detail})",
                    resolved_url=resolved_via_search,
                )

        # Wait for late JS / lazy-loaded content to settle after domcontentloaded
        time.sleep(5)

        def _scroll_full(sleep_between: float = 0.5) -> None:
            """Scroll from top to bottom in ~15 steps to trigger lazy loads."""
            h = page.evaluate("document.body.scrollHeight")
            step = max(600, h // 15)
            y = 0
            while y < h:
                page.evaluate(f"window.scrollTo(0, {y})")
                time.sleep(sleep_between)
                y += step
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        # Pass 1: scroll to trigger initial lazy loads
        _scroll_full(0.5)
        time.sleep(2)

        # Expand collapsed article bodies (e-nomothesia hides article text by default)
        found_expand = expand_articles(page)
        if found_expand:
            time.sleep(3)   # wait for all articles to expand and reflow
            # Pass 2: re-scroll because the page is now much taller
            _scroll_full(0.5)
            time.sleep(3)   # final content settle
        else:
            time.sleep(3)   # still settle even without expand

        # Dismiss cookie/consent popup + hide all fixed/sticky before printing
        dismiss_consent(page)

        # In test mode: report what fixed/sticky elements remain (should be none/empty)
        if test_mode:
            elements = diagnose_fixed_sticky(page)
            print()
            print("--- FIXED/STICKY ELEMENTS after dismiss_consent (should be empty) ---")
            if not elements:
                print("  (none -- all hidden successfully)")
            for e in elements:
                print(
                    f"  <{e['tag']}> id={e['id']!r} pos={e['position']} z={e['zIndex']} "
                    f"box=({e['x']},{e['y']},{e['w']}x{e['h']})"
                )
                if e.get("cls"):
                    print(f"    class: {e['cls']}")
                if e.get("text"):
                    print(f"    text:  {e['text']!r}")
            print(f"Total: {len(elements)} element(s)")
            print()

        page.pdf(
            path=str(dest),
            format="A4",
            print_background=True,
            display_header_footer=False,
        )

        char_count = count_text_chars(dest)
        status = classify(char_count)
        return DownloadResult(
            filename=row.filename,
            url=row.url,
            note=row.note,
            status=status,
            char_count=char_count,
            resolved_url=resolved_via_search,
        )

    except Exception as exc:
        return DownloadResult(
            filename=row.filename,
            url=row.url,
            note=row.note,
            status="FAILED",
            error=str(exc)[:200],
        )


def build_report(results: list[DownloadResult]) -> str:
    ok = [r for r in results if r.status == "OK"]
    low = [r for r in results if r.status in ("LOW_TEXT", "EMPTY")]
    failed = [r for r in results if r.status == "FAILED"]
    todo = [r for r in results if r.status == "TODO"]

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("DOWNLOAD REPORT -- e-nomothesia.gr law PDFs")
    lines.append("=" * 70)
    lines.append("")

    lines.append(f"SUCCEEDED (OK): {len(ok)}")
    for r in ok:
        lines.append(f"  [OK] {r.filename}  ({r.char_count:,} chars)  -- {r.note}")

    lines.append("")
    lines.append(f"NEEDS MANUAL CHECK (LOW_TEXT / EMPTY): {len(low)}")
    for r in low:
        lines.append(f"  [!!] {r.filename}  [{r.status}, {r.char_count:,} chars]")
        lines.append(f"      URL:  {r.url}")
        lines.append(f"      Note: {r.note}")

    lines.append("")
    lines.append(f"FAILED (HTTP error / timeout): {len(failed)}")
    for r in failed:
        lines.append(f"  [X]  {r.filename}  [{r.error}]")
        lines.append(f"      URL:  {r.url}")
        lines.append(f"      Note: {r.note}")

    lines.append("")
    lines.append(f"TODO (manual OCR -- not downloaded): {len(todo)}")
    for r in todo:
        lines.append(f"  [ ]  {r.filename}  -- {r.note}")

    # RESOLVED VIA SEARCH — URLs discovered by site search (update manifest with these)
    resolved = [r for r in results if r.resolved_url]
    lines.append("")
    lines.append(f"RESOLVED VIA SEARCH (update manifest with these URLs): {len(resolved)}")
    for r in resolved:
        tag = "[OK]" if r.status == "OK" else f"[{r.status}]"
        lines.append(f"  {tag} {r.filename}")
        lines.append(f"      {r.resolved_url}")

    lines.append("")
    lines.append(
        f"SUMMARY: {len(ok)} OK  |  {len(low)} LOW/EMPTY  |  {len(failed)} FAILED  |  {len(todo)} TODO"
        + (f"  |  {len(resolved)} resolved-via-search" if resolved else "")
    )
    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download law PDFs from e-nomothesia.gr")
    parser.add_argument(
        "--test",
        action="store_true",
        help=f"Download only {TEST_FILENAME} to verify cookie-consent dismissal",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-attempt only rows whose output file does not yet exist in new/ (keep existing PDFs)",
    )
    parser.add_argument(
        "--only",
        metavar="FILE1,FILE2,...",
        help=(
            "Re-download only the listed filenames (comma-separated). "
            "Files are written to data/raw_pdfs/public/, overwriting existing copies. "
            "No purge of any other folder. Example: --only N1337-1983-Eisfores.pdf,N3852-2010-Kallikratis.pdf"
        ),
    )
    args = parser.parse_args()

    if not check_playwright():
        print(
            "ERROR: Playwright is not installed.\n"
            "Install with:\n"
            "  uv pip install playwright\n"
            "  uv run playwright install chromium"
        )
        sys.exit(1)

    from playwright.sync_api import sync_playwright

    rows = load_manifest()
    ensure_dirs(rows)

    auto_rows = [r for r in rows if r.method == "auto"]
    manual_rows = [r for r in rows if r.method == "manual_ocr"]

    if args.only:
        # Re-download specific files into public/ (overwrite truncated/stale copies).
        # No purge of any folder.
        only_set = {f.strip() for f in args.only.split(",") if f.strip()}
        rows_to_run = [r for r in auto_rows if r.filename in only_set]
        unrecognised = only_set - {r.filename for r in rows_to_run}
        if unrecognised:
            print(f"WARNING: filenames not found in manifest: {unrecognised}")
        # Override destination folder to public/ for all --only rows
        public_dir = OUTPUT_BASE / "public"
        public_dir.mkdir(parents=True, exist_ok=True)
        print(f"--only mode: re-downloading {len(rows_to_run)} file(s) into data/raw_pdfs/public/")
        print()
    elif args.retry_failed:
        # Skip any file that already exists — only attempt the missing ones.
        # Do NOT purge existing PDFs.
        new_dir = OUTPUT_BASE / "new"
        rows_to_run = [r for r in auto_rows if not (new_dir / r.filename).exists()]
        skipped = len(auto_rows) - len(rows_to_run)
        print(f"--retry-failed mode: {skipped} already exist (kept), {len(rows_to_run)} to attempt")
        print()
    elif args.test:
        purge_new_pdfs()
        test_rows = [r for r in auto_rows if r.filename == TEST_FILENAME]
        if not test_rows:
            print(f"ERROR: {TEST_FILENAME} not found in manifest.")
            sys.exit(1)
        print(f"--test mode: downloading {TEST_FILENAME} only")
        print()
        rows_to_run = test_rows
    else:
        purge_new_pdfs()
        print(f"Manifest: {len(auto_rows)} auto, {len(manual_rows)} manual_ocr")
        print()
        rows_to_run = auto_rows

    results: list[DownloadResult] = []

    PW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # Persistent context: consent cookie survives across pages in this session
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PW_PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for i, row in enumerate(rows_to_run, 1):
            # --only always writes to public/ (overwriting truncated copies in place)
            if args.only:
                dest = OUTPUT_BASE / "public" / row.filename
            else:
                dest = OUTPUT_BASE / row.folder / row.filename
            print(f"[{i}/{len(rows_to_run)}] {row.filename} ...", end=" ", flush=True)
            result = download_one(page, row, dest, test_mode=args.test)
            results.append(result)

            status_display = result.status
            if result.status == "FAILED":
                status_display = f"FAILED ({result.error})"
            elif result.status in ("OK", "LOW_TEXT", "EMPTY"):
                status_display = f"{result.status} ({result.char_count:,} chars)"
            print(status_display)

            if i < len(rows_to_run):
                time.sleep(random.uniform(2.0, 3.0))

        context.close()

    # In full mode (not --test / --retry-failed / --only), append TODO entries
    if not args.test and not args.retry_failed and not args.only:
        for row in manual_rows:
            results.append(DownloadResult(
                filename=row.filename,
                url=row.url,
                note=row.note,
                status="TODO",
            ))

    report = build_report(results)
    print()
    print(report)

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {REPORT_PATH}")

    if args.test:
        dest = OUTPUT_BASE / "new" / TEST_FILENAME
        print(f"PDF written to:  {dest}")

        # Programmatic consent-text check
        pdf_text = extract_all_text(dest)
        probe = "e-nomothesia.gr ζητά τη συναίνεση"
        if probe in pdf_text:
            print(f"\nCONSENT CHECK: FAIL -- consent text found in PDF.")
            print(f'  Searched for: "{probe}"')
        else:
            print(f"\nCONSENT CHECK: PASS -- consent text NOT found in PDF.")
            print("  Open the PDF to visually confirm the popup is gone.")


if __name__ == "__main__":
    main()
