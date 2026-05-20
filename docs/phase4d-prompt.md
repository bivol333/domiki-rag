# Phase 4d: Corpus Quality - Text Cleanup + Robust Structure Detection

Read `CLAUDE.md` first. The system is live and working. We just expanded the corpus from 3 to ~11 PDFs and hit a problem: 3 PDFs fail during ingestion at the chunking/structure stage.

## Background - what we diagnosed

We ran a diagnostic. All 3 failing PDFs (`N4178-2013-Old-Authaireta-Codified-202512.pdf`, `PD-41-2018-Pyroprostasia.pdf`, `n44952017-demo.pdf`) **extract text fine** via PyMuPDF but **fail in the chunking/structure stage**.

The failing PDFs were created by browser "Print to PDF" from e-nomothesia.gr, and contain webpage noise that the original clean PDFs did not:

- Private-use Unicode glyphs (icon fonts): `\uf39e \uf099 \uf0e1 \uf09e \uf0e0 \uf07a0 \uf007` etc.
- Non-breaking spaces: `\xa0`
- Website chrome text: "Σύνδεση", "Συνδρομητικές Υπηρεσίες", "Τράπεζα Πληροφοριών e-nomothesia.gr"
- Likely page headers/footers repeated across pages

The corpus now mixes legal Greek of different eras: modern δημοτική (Ν. 4495/2017) AND καθαρεύουσα (Ν. 998/1979, with forms like "Άρθρον", "η χορήγησις", "ανέγερσις").

## Goal of this phase

Make ingestion robust to:
1. Webpage noise from print-to-PDF sources
2. Article-heading variations (καθαρεύουσα, uppercase, abbreviations)
3. PDFs where no articles are detected (graceful fallback instead of failure)

After this phase, all 11 PDFs must ingest successfully with clean chunks.

## Step 0 - FIRST, reproduce the exact error

Before changing anything, find the actual exception. Write a temporary diagnostic that runs the REAL ingestion pipeline on ONE failing file (`PD-41-2018-Pyroprostasia.pdf`) and prints the full traceback. Report to me:
- The exact exception type and message
- Which module/function raises it (structure_detector? chunker? metadata_extractor?)
- Whether it's a crash (exception) or a silent "0 chunks produced"

Show me this finding before proceeding to fixes. This confirms our hypothesis.

## Deliverables (after Step 0 confirms the cause)

```
src/ingestion/text_cleaner.py       # NEW: cleanup/normalization module
src/ingestion/structure_detector.py # MODIFY: broaden article regex, handle variations
src/ingestion/chunker.py            # MODIFY: graceful fallback when 0 articles
src/ingestion/pipeline.py           # MODIFY: call text_cleaner after parsing, before structure detection
tests/test_text_cleaner.py          # NEW
tests/test_structure_detector.py    # MODIFY: add καθαρεύουσα + variation cases
```

## Implementation specifications

### `src/ingestion/text_cleaner.py` (NEW)

A `clean_legal_text(text: str, source_hint: str = "") -> str` function that:

1. **Removes private-use Unicode glyphs**: strip characters in range U+E000-U+F8FF (these are icon fonts, never legal content)

2. **Normalizes whitespace**:
   - Replace `\xa0` (nbsp) with regular space
   - Collapse multiple spaces/tabs to single space
   - Normalize to Unicode NFC (consistent with existing tokenizer)
   - Preserve paragraph breaks (double newlines)

3. **Removes known webpage chrome** (case-insensitive, whole-line matching). Remove lines that are exactly or predominantly these:
   - "Σύνδεση"
   - "Συνδρομητικές Υπηρεσίες" (and lines starting with it)
   - "Τράπεζα Πληροφοριών"
   - "e-nomothesia.gr" (standalone navigation references)
   - "Εκτύπωση επιλεγμένων", "Προσωπικές σημειώσεις", "Μελέτη νόμου"
   - Cookie consent fragments: lines containing "cookies" + "Ρυθμίσεις"
   - Pure navigation: lines that are just "Επόμενο άρθρο", "Προηγούμενο άρθρο", "Μετάβαση στα περιεχόμενα"

   IMPORTANT: Be conservative. Only strip lines that are clearly chrome, never legal text. When unsure, keep the line. Use a curated blocklist of exact/prefix patterns, NOT aggressive heuristics.

4. **Removes repeated headers/footers**: if the same short line (< 80 chars) appears on most pages (e.g. > 50% of pages), it's likely a header/footer - remove it. (This requires page-aware processing - if the pipeline passes text per-page, detect repeats; if it passes full text, skip this sub-step and note it.)

5. **Logs** what it removed (counts per category) so we can audit.

Make the cleaner conservative and well-tested. Over-aggressive cleaning that removes legal content is worse than leaving some noise.

### `src/ingestion/structure_detector.py` (MODIFY)

Broaden the article-heading regex to match all these variants (case-insensitive where appropriate):

- `Άρθρο 5`, `Άρθρο 5α`, `Άρθρο 5Α`
- `Άρθρον 5` (καθαρεύουσα)
- `ΑΡΘΡΟ 5`, `ΑΡΘΡΟΝ 5` (uppercase)
- `Άρθ. 5`, `Αρθρ. 5`, `Αρθ. 5` (abbreviations)
- With or without tonos: `Αρθρο` / `Άρθρο`
- Optional period/colon after number: `Άρθρο 5.`, `Άρθρο 5:`

Suggested approach: a single robust regex with alternation, anchored to line start (after optional whitespace), e.g.:
```python
ARTICLE_PATTERN = re.compile(
    r"^\s*(?:ΆΡΘΡΟ[Ν]?|Άρθρο[ν]?|Αρθρο[ν]?|ΑΡΘ\.|Άρθ\.|Αρθρ\.|Αρθ\.)\s*"
    r"(\d+)\s*([Α-Ωα-ω]?)",
    re.IGNORECASE | re.MULTILINE,
)
```
Tune as needed. Add unit tests for each variant.

Also handle paragraph detection variants if the current code does paragraph-level splitting: `παρ. 5`, `παράγραφος 5`, `5.`, `(5)`, `α)`, `1)`.

### `src/ingestion/chunker.py` (MODIFY)

Add graceful fallback: if structure detection yields **zero articles** for a document:
- Log a clear warning: `"No articles detected in {source}, falling back to sliding-window chunking"`
- Chunk the document using sliding-window (e.g. ~600 tokens with ~100 token overlap) instead of raising an exception
- These chunks get generic metadata (no article number, but keep source_file, page numbers)

This ensures a PDF NEVER fails ingestion just because its structure is unusual - worst case it gets window-chunked.

### `src/ingestion/pipeline.py` (MODIFY)

Insert the cleanup step: after PDF parsing, before structure detection, run `clean_legal_text()` on the extracted text. Make sure the page/position info needed downstream still works (if cleanup changes text length, ensure page mapping isn't broken - if it is, clean per-page).

Also improve error reporting: when a file fails, log the actual exception + traceback to a log, and in the summary print the reason category (parse error / zero chunks / exception in X), not just the filename.

## Testing requirements

`tests/test_text_cleaner.py`:
1. Private-use glyphs removed (`\uf0e1` etc. stripped)
2. `\xa0` normalized to space
3. Known chrome lines removed ("Συνδρομητικές Υπηρεσίες" etc.)
4. Legal text with the word "σύνδεση" in a real sentence is NOT removed (only standalone nav)
5. NFC normalization applied
6. Conservative: a line of real legal text is never stripped

`tests/test_structure_detector.py` (extend):
7. Detects "Άρθρον 5" (καθαρεύουσα)
8. Detects "ΑΡΘΡΟ 5" (uppercase)
9. Detects "Άρθ. 5" (abbreviation)
10. Detects "Άρθρο 5α" (with letter suffix)
11. Existing modern "Άρθρο 5" still works (no regression)

Plus ensure all existing tests (should be ~142) still pass.

## Acceptance criteria

- [ ] Step 0 diagnosis reported to me before fixes
- [ ] All existing tests still pass
- [ ] New text_cleaner tests pass
- [ ] Extended structure_detector tests pass
- [ ] Re-running ingestion on all 11 PDFs: **0 failures** (or, if a file genuinely can't be processed, a clear logged reason - not a silent failure)
- [ ] The 3 previously-failing PDFs now produce chunks
- [ ] Spot-check: chunks from cleaned PDFs do NOT contain "Συνδρομητικές Υπηρεσίες" or `\uf0XX` glyphs
- [ ] `uv run ruff check src/ scripts/ tests/` clean

## Important constraints

- Do NOT touch the live deployed system or cloud Qdrant yet - we re-ingest and migrate separately after this is verified locally
- Be CONSERVATIVE with text cleaning - removing legal content is far worse than leaving minor noise
- Preserve the deterministic md5-based tokenization (don't break tokenizer parity)
- The cleanup must not break page-number metadata

## Workflow

1. Step 0: reproduce + report the exact error. WAIT for my acknowledgment.
2. After I confirm: implement text_cleaner, structure_detector changes, chunker fallback, pipeline integration
3. Run tests
4. Re-ingest locally (I'll run this or you can): report new chunk count + 0 failures
5. Report summary. We then handle cloud migration separately.

Before Step 0, ask any clarifying questions.
