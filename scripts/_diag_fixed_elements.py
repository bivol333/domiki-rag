"""
Step-1 diagnostic: list all fixed/sticky elements on the test page.
Run after consent dismissal, before printing.
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PW_PROFILE_DIR = PROJECT_ROOT / "data" / ".pw_profile"
TEST_URL = "https://www.e-nomothesia.gr/kat-periballon/antiseismikos-kanonismos/ya-upen-daoka-66006-2360-2023.html"

_ACCEPT_LABELS = [
    "συναίνεση", "αποδοχή όλων", "αποδοχή", "αποδέχομαι", "συμφωνώ",
    "accept all", "accept", "ok",
]

DIAG_JS = """
() => {
    const results = [];
    const vw = window.innerWidth, vh = window.innerHeight;
    document.querySelectorAll('*').forEach(el => {
        const st = window.getComputedStyle(el);
        const pos = st.position;
        const zi  = parseInt(st.zIndex) || 0;
        const r   = el.getBoundingClientRect();
        const isFixedSticky = (pos === 'fixed' || pos === 'sticky');
        const isHighZ = zi > 50 && r.width > vw * 0.4;
        if (isFixedSticky || isHighZ) {
            results.push({
                tag:      el.tagName,
                id:       el.id || '',
                cls:      (el.className && typeof el.className === 'string')
                              ? el.className.slice(0, 120) : '',
                position: pos,
                zIndex:   st.zIndex,
                x:        Math.round(r.x),
                y:        Math.round(r.y),
                w:        Math.round(r.width),
                h:        Math.round(r.height),
                text:     (el.innerText || '').replace(/\\s+/g,' ').slice(0, 80),
            });
        }
    });
    return results;
}
"""

def dismiss_consent(page):
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            if page.locator("text=Συναίνεση").count() > 0:
                break
            for frame in page.frames[1:]:
                if frame.locator("text=Συναίνεση").count() > 0:
                    break
        except Exception:
            pass
        time.sleep(0.3)

    all_frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for frame in all_frames:
        try:
            candidates = frame.query_selector_all(
                "button, a[role=button], input[type=button], input[type=submit], [role=button]"
            )
        except Exception:
            continue
        for el in candidates:
            try:
                label = (el.inner_text() or "").strip().lower()
            except Exception:
                label = ""
            for pat in _ACCEPT_LABELS:
                if pat in label:
                    try:
                        el.click()
                        time.sleep(1.0)
                    except Exception:
                        pass
                    break

    time.sleep(1.0)


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed"); sys.exit(1)

    PW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PW_PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        print(f"Loading: {TEST_URL}")
        page.goto(TEST_URL, wait_until="networkidle", timeout=60_000)

        # Scroll to load lazy content
        h = page.evaluate("document.body.scrollHeight")
        step = max(800, h // 10)
        y = 0
        while y < h:
            page.evaluate(f"window.scrollTo(0,{y})")
            time.sleep(0.15)
            y += step
        page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
        time.sleep(2)

        dismiss_consent(page)

        print("\n--- FIXED/STICKY ELEMENTS (before any hide) ---")
        elements = page.evaluate(DIAG_JS)
        if not elements:
            print("  (none found)")
        for e in elements:
            print(
                f"  <{e['tag']}> pos={e['position']} z={e['zIndex']} "
                f"box=({e['x']},{e['y']},{e['w']}x{e['h']})"
            )
            if e['id']:
                print(f"    id:    {e['id']}")
            if e['cls']:
                print(f"    class: {e['cls']}")
            if e['text']:
                print(f"    text:  {e['text']!r}")
        print(f"\nTotal: {len(elements)} element(s)")

        ctx.close()


if __name__ == "__main__":
    main()
