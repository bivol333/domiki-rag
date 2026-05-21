"""Audit the local Qdrant collection after Phase 4d fixes.

Checks:
1. Metadata correctness - law_number and source_type per source file
2. Noise contamination - footer URLs and PUA glyphs in chunk text
3. Chunk distribution per source file

Run from project root:
    uv run python scripts/audit_collection.py
"""

import re
from collections import defaultdict

from qdrant_client import QdrantClient

from src.config import settings

COLLECTION = "domiki_public"

# PUA range (icon font glyphs)
PUA_RE = re.compile(r"[\ue000-\uf8ff]")
# Standalone URL pattern
URL_RE = re.compile(r"https?://[^\s]+")


def main() -> None:
    client = QdrantClient(url=settings.qdrant_url)

    total = client.count(COLLECTION).count
    print(f"Collection: {COLLECTION}")
    print(f"Total chunks: {total}\n")

    # Scroll through all points
    by_source: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "law_numbers": set(),
            "source_types": set(),
            "articles": set(),
            "url_noise": 0,
            "pua_noise": 0,
        }
    )

    offset = None
    scanned = 0
    while True:
        points, offset = client.scroll(
            COLLECTION,
            limit=200,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            source = payload.get("source_file", "UNKNOWN")
            text = payload.get("text", "")

            s = by_source[source]
            s["count"] += 1
            if payload.get("law_number"):
                s["law_numbers"].add(payload["law_number"])
            if payload.get("source_type"):
                s["source_types"].add(payload["source_type"])
            if payload.get("article"):
                s["articles"].add(payload["article"])
            if URL_RE.search(text):
                s["url_noise"] += 1
            if PUA_RE.search(text):
                s["pua_noise"] += 1

            scanned += 1

        if offset is None:
            break

    print(f"Scanned {scanned} chunks across {len(by_source)} source files\n")
    print("=" * 80)

    total_url_noise = 0
    total_pua_noise = 0

    for source in sorted(by_source.keys()):
        s = by_source[source]
        total_url_noise += s["url_noise"]
        total_pua_noise += s["pua_noise"]

        print(f"\nFILE: {source}")
        print(f"  Chunks: {s['count']}")
        print(f"  law_number: {sorted(s['law_numbers']) or 'MISSING'}")
        print(f"  source_type: {sorted(s['source_types']) or 'MISSING'}")
        print(f"  distinct articles: {len(s['articles'])}")
        if s["url_noise"]:
            print(f"  WARNING: {s['url_noise']} chunks still contain URLs")
        if s["pua_noise"]:
            print(f"  WARNING: {s['pua_noise']} chunks still contain PUA glyphs")
        # Flag suspicious: multiple law numbers in one file = likely cross-reference contamination
        if len(s["law_numbers"]) > 1:
            print("  FLAG: multiple law_numbers in one file - possible metadata contamination")
        if not s["law_numbers"]:
            print("  FLAG: no law_number detected")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print(f"  Total chunks with URL noise: {total_url_noise}")
    print(f"  Total chunks with PUA noise: {total_pua_noise}")
    print(f"  Source files: {len(by_source)}")

    if total_url_noise == 0 and total_pua_noise == 0:
        print("\n  CLEAN: No noise contamination detected.")
    else:
        print("\n  ATTENTION: Some noise remains - review flagged files above.")


if __name__ == "__main__":
    main()
