# Architecture & engineering decisions

The goal is **Question → correct source passage → correct page reference**, with the scanned PDF as
the final authority. This document records how the system is built, and why.

## 1. What the source PDF actually looks like

An inspection of `sources/fazail-e-amal.pdf` (1009 pages) drove most decisions:

| Finding | Consequence |
|---|---|
| Every page is a 300-dpi bitonal scan (JBIG2); **no text layer**. | OCR is required for every page. |
| Main text is **Bangla in old literary style** (সাধু ভাষা: করিয়াছেন, হইতে) with old spellings (ফযীলত, ছদকা, নামায). Arabic and Urdu blocks appear, often side by side. | Search must bridge modern user spelling ↔ book spelling (§4). Layout must handle RTL columns. |
| A **running header** in a box names the sub-book or chapter plus its own page count (`ফাযায়েলে কুরআন-৭৬`, `দ্বিতীয় অধ্যায়-৯৯`). | Headers give sections for free (§3). Header numbers are *not* book pages. |
| The **printed book page** is a Bangla number in a box at the bottom centre (`২৬৬`). Some pages also have a printer's mark such as `—৩` at the bottom-left. | Footer detection accepts only a centred, non-dash number. |
| **The PDF→printed offset drifts**: PDF 4→৬ (+2), 11→১৪ (+3), 263→২৬৬ (+3), 601→৬০৮ (+7). | Never assume an offset; detect per page and verify against neighbours (§2). |
| **Six printed pages were split into two narrow PDF pages** by the scanner (PDF 189+190, 199+200, 603+604, 869+870, 875+876, 971+972) — both PDF pages crop the same scan. | Detected automatically and stitched back into one page image; OCR'd once; cited as "PDF 189–190" (§2). |

## 2. Ingestion pipeline (`backend/ingestion/`)

```
PDF ─render─> page PNG (2400 px, OCR) + 4-level grey PNG (1600 px, viewer ~160 KB)
    ─ocr────> OcrPage JSON  (blocks → lines → words, pixel boxes, confidences)
    ─layout─> PageLayout JSON (running header, footer number, paragraphs, headings, script, boxes)
    ─structure> printed-page mapping + section tree + review CSVs
    ─load───> PostgreSQL rows (pages, sections, paragraphs, chunks)
    ─embed──> pgvector rows (disk-cached; never re-paid)
    ─upload─> object storage (original PDF + page images)
```

* **OCR engine: Google Cloud Vision** `DOCUMENT_TEXT_DETECTION` with `bn/ar/ur` hints. Chosen for
  Bangla accuracy, mixed-script pages, word-level boxes, and because it is *deterministic*. An
  LLM-vision OCR was rejected: it can silently "fix" or invent words, which breaks the promise
  that the quoted text is the book's text. Tesseract is available as an offline fallback.
* **Paragraphs** are rebuilt from OCR lines with layout rules that match this typesetting: a new
  paragraph starts at a first-line indent, after a line that stops short of the right margin, after
  extra vertical space, at a numbered hadith `(৩৬)`, or at a script change. Attribution lines like
  `(তাবারানী)` are attached to their paragraph; tiny fragments are merged. When unsure, lines stay
  together: a slightly longer paragraph is harmless, a sentence split across two sources is not.
* **Page-break paragraphs**: if a page ends mid-sentence at full width and the next page starts
  without indent, the two halves are linked. The source card shows both halves, each with its own
  page numbers, and the embedding sees the joined text.
* **Printed page numbers** (`page_numbers.py`): the footer reading becomes an *anchor* only if a
  nearby page agrees on the same offset. Anchors must form a longest increasing subsequence, and a
  printed number may never advance faster than the scan. Gaps are filled only when the arithmetic
  is unambiguous. Everything else is marked `unknown` and listed for review, never guessed.
  `page_mapping.json` / `ingestion set-page` overrides win. Every page stores its `printed_page_source`
  (`manual | ocr | inferred | unknown`), and the UI shows it.
* **Sections** (`sections.py`): non-chapter headers give sub-books (level 1); chapter headers
  (অধ্যায়/পরিচ্ছেদ) give chapters (level 2) nested under the latest sub-book. Fuzzy clustering plus a
  sliding majority vote absorbs OCR noise in headers. `sections.json` overrides.
* **Chunking**: one chunk per paragraph. Paragraphs over 1400 characters are split on sentence
  boundaries (`।`, `?`, …) into contiguous exact slices (`char_start/char_end`), so a chunk is always
  a substring of its paragraph and the whole paragraph can be shown.
* **Stable ids**: `chunk_` + sha1(book, pdf page, paragraph index, chunk index)[:10].

## 3. Data model (PostgreSQL + pgvector)

`books` → `documents` (source file + sha256, storage key) → `pages` (pdf page, printed page +
source, header, image key, OCR confidence, `needs_review`) → `paragraphs` (exact text, boxes,
section/chapter, continuation flags) → `chunks` (retrieval unit, folded search key, generated
`tsvector`) → `embeddings` (`vector(1024)`, per model, HNSW index). `sections` is a self-referencing
tree. `query_logs` records per-request diagnostics. The PDF binary and images live in object storage;
the database stores keys only.

## 4. Retrieval (`backend/app/retrieval/`)

```
question ─LLM query plan─> standalone question, 2-4 Bangla paraphrases (one in the book's style),
                            spelling-variant keywords, a hypothetical book-style passage (HyDE)
         ─retrievers─────> pgvector (≤6 query vectors, exact scan) · full-text · trigram
         ─RRF fusion─────> top 30 paragraphs
         ─rerank─────────> relevance 0..1, threshold
         ─select─────────> top 5 above threshold (or "insufficient evidence")
```

* **Bangla keyword search.** Text is folded into an ASCII phonetic key (`app/core/textnorm.py`)
  before indexing. Spelling variants collapse: য/জ, ী/ি, ূ/ু, শ/ষ/স/ছ, ো/ু, nukta forms, doubled
  consonants, plus light suffix stemming (সদকার→সদকা, নামাযের→নামায). So `সদকার ফজিলত` matches
  `ছদকার ফযীলত`. ASCII keys also make PostgreSQL full-text and trigram behave the same whatever the
  server locale (Bengali vowel signs can otherwise split words). The key is only used for search.
* **Trigram** matching catches OCR slips and variants that folding misses.
* **Vector search** runs as an exact scan by default. With about 10–20k chunks this costs tens of ms
  and gives 100% recall; set `VECTOR_SEARCH_MODE=hnsw` if the corpus grows large.
* **Reranking**: the default is a listwise LLM judge (strict 0–10 rubric, aliased ids, passages
  treated as data). Cohere `rerank-v3.5` / Jina multilingual are drop-in alternatives. If the reranker
  fails, the fusion order is used and the failure is logged.
* **The unit is the paragraph.** The model and the user see complete paragraphs, plus page-break
  neighbours.

## 5. Generation and the anti-hallucination boundary

1. The LLM receives the selected paragraphs as `<source id="chunk_…">` blocks and must cite ids
   inline. It is told to answer only from them, not to quote at length, and to emit
   `[[INSUFFICIENT_EVIDENCE]]` when they don't answer the question.
2. `citation/verify.py` rewrites the answer, keeping only ids that were **actually given to the
   model for this request**. Invented or altered ids are removed and logged.
3. Every source object (`original_text`, pages, section, image URL) is **re-read from the database
   by id**. Nothing the model writes is ever displayed as source text.
4. The UI renders citation chips only for ids present in the verified `sources` list, labels the
   passage "exact original text from the database", and links the scanned page with the OCR line
   boxes highlighted, so any OCR error is immediately visible against the image.
5. If nothing passes the relevance threshold, the model is not called and the user is told the
   book passages do not provide enough evidence.

## 6. Security

Secrets only in the backend `.env` (never logged; `Settings.safe_dict` redacts them; HTTP-client
loggers are silenced because some APIs put keys in URLs, and Vision/Gemini keys are sent in headers).
CORS allow-list, slowapi rate limits (Redis-backed when `REDIS_URL` is set), Pydantic input
validation with length caps, parameterised SQL only, a storage key path-traversal guard, and
security headers. The frontend holds no keys. There are no uploads in the MVP.

## 7. What "99% accurate" means here, and how to get there

The pipeline is built to make each failure mode visible and correctable rather than silent:

| Risk | Mitigation | Where to check |
|---|---|---|
| OCR misreads a word | Deterministic OCR; the scan is always one click away with the paragraph highlighted; low-confidence pages flagged | `pages.ocr_confidence`, viewer |
| Wrong printed page | Neighbour-verified anchors, no guessing, manual overrides | `reports/page_numbers.csv`, `ingestion report` |
| Wrong passage retrieved | Hybrid retrieval + variant folding + LLM query plan + reranking | `eval.run_eval`, debug panel |
| Answer adds unsupported claims | Grounded prompt + citation filter + groundedness judge in eval | `eval.run_eval --mode e2e --judge` |
| Fabricated citation | Structurally impossible: only ids given to the model survive, and text is re-read from the DB | tests `test_sanitize_*`, integration test |

Recommended acceptance process after ingesting: review `page_numbers.csv` (fix every `unknown` /
`conflict` row), run `eval.run_eval` on the curated set and on a ≥150-question synthetic set, and
inspect every miss in the debug panel. Misses are usually a layout rule, a missing spelling variant,
or a threshold, and each is a one-line fix plus a re-run of `layout,structure,load,embed` from cache.

## 8. Choices worth revisiting

* **Embedding model**: the default is `gemini-embedding-001` @1024-d. Compare `local` bge-m3 and
  Cohere multilingual with `eval.run_eval` before finalising. Changing the dimension needs a migration.
* **Model cost/latency**: `LLM_FAST_MODEL` can point query understanding and reranking at a cheaper
  model; measure with the eval set first.
* **Section titles** depend on header OCR. Check `reports/sections.csv` once; `sections.json` fixes
  anything odd permanently.
