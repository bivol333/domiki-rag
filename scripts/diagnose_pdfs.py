"""Diagnostic script to investigate why certain PDFs failed during ingestion.

Run from project root:
    uv run python scripts/diagnose_pdfs.py
"""

import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF (fitz) not available")
    sys.exit(1)

# The files that failed during ingestion
FAILED_FILES = [
    "N4178-2013-Old-Authaireta-Codified-202512.pdf",
    "PD-41-2018-Pyroprostasia.pdf",
    "n44952017-demo.pdf",
]

BASE = Path("data/raw_pdfs/public")


def diagnose(fname: str) -> None:
    fpath = BASE / fname
    print(f"\n{'=' * 60}")
    print(f"FILE: {fname}")
    print(f"{'=' * 60}")

    if not fpath.exists():
        print("  STATUS: FILE NOT FOUND")
        # Try to find similar names
        if BASE.exists():
            similar = [f.name for f in BASE.glob("*.pdf") if fname[:10].lower() in f.name.lower()]
            if similar:
                print(f"  Similar files found: {similar}")
        return

    size_kb = fpath.stat().st_size / 1024
    print(f"  Size: {size_kb:.1f} KB")

    if size_kb < 5:
        print("  WARNING: File is suspiciously small (<5KB) - likely empty/corrupt")

    # Try PyMuPDF
    try:
        doc = fitz.open(str(fpath))
        print(f"  Pages: {doc.page_count}")

        if doc.page_count == 0:
            print("  WARNING: Zero pages")
            doc.close()
            return

        # Check text extraction across first few pages
        total_text = 0
        empty_pages = 0
        for i in range(min(5, doc.page_count)):
            page_text = doc[i].get_text()
            total_text += len(page_text)
            if len(page_text.strip()) < 10:
                empty_pages += 1

        print(f"  Text in first {min(5, doc.page_count)} pages: {total_text} chars")
        print(f"  Near-empty pages: {empty_pages}")

        # Sample from page 1
        page1_text = doc[0].get_text()
        sample = page1_text[:200].replace("\n", " ")
        print(f"  Page 1 sample: {sample!r}")

        if total_text < 50:
            print("  DIAGNOSIS: Likely image-based PDF (scanned/printed as image) - needs OCR")
        elif empty_pages > 0:
            print("  DIAGNOSIS: Some pages have no extractable text - mixed content")
        else:
            print(
                "  DIAGNOSIS: Text extracts fine via PyMuPDF"
                " - failure is likely in chunking/structure stage, not parsing"
            )

        # Check for encoding issues (mojibake)
        if page1_text and any(ord(c) > 0x2000 and ord(c) < 0x2100 for c in page1_text[:500]):
            # This range can indicate some encoding artifacts
            pass

        doc.close()

    except Exception as e:
        print(f"  PyMuPDF ERROR: {type(e).__name__}: {e}")
        print("  DIAGNOSIS: File is corrupt or not a valid PDF")


def main() -> None:
    print("PDF Diagnostic Report")
    print(f"Base directory: {BASE.resolve()}")

    if not BASE.exists():
        print(f"ERROR: Directory {BASE} does not exist")
        sys.exit(1)

    # List all PDFs present
    all_pdfs = sorted(BASE.glob("*.pdf"))
    print(f"\nAll PDFs in directory ({len(all_pdfs)}):")
    for p in all_pdfs:
        print(f"  - {p.name} ({p.stat().st_size / 1024:.0f} KB)")

    # Diagnose the failed ones
    for fname in FAILED_FILES:
        diagnose(fname)

    print(f"\n{'=' * 60}")
    print("Diagnosis complete. Share this output.")


if __name__ == "__main__":
    main()
