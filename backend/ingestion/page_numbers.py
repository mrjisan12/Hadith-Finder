"""PDF page -> printed book page mapping.

The scanned book's PDF page numbers and printed page numbers differ, and the offset is NOT
constant (it drifts: e.g. PDF 4 -> ৬, PDF 11 -> ১৪, PDF 601 -> ৬০৮) because of unnumbered
plates, title pages, etc. So we never assume an offset. Instead:

1. OCR reads the footer number on every page ("detected").
2. A detection becomes an *anchor* only when a nearby page's detection agrees with it
   (same offset). This rejects single OCR misreads (৩/৬/৯ confusions etc.).
3. Anchors must increase monotonically (longest increasing subsequence); outliers are dropped.
   Numbering restarts, if a book has them, are declared in page_mapping.json.
4. Gaps between two anchors are filled only when the arithmetic is unambiguous
   (number of pages in the gap == number of printed numbers in the gap).
5. Manual overrides from `page_mapping.json` win over everything.

Every page gets a `source`: manual | ocr | inferred | unknown, and ambiguous pages are
flagged for review instead of guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

WINDOW = 4
MAX_PRINTED = 5000


@dataclass
class PageNumberResult:
    pdf_page: int
    detected: int | None
    printed: int | None
    label: str | None
    source: str  # manual | ocr | inferred | unknown
    flag: str | None = None  # conflict | unverified | ambiguous_gap | None


def _find_anchors(detected: dict[int, int | None]) -> dict[int, int]:
    pages = sorted(detected)
    valid = {p: d for p, d in detected.items() if d is not None and 0 < d < MAX_PRINTED}
    anchors: dict[int, int] = {}
    for p in pages:
        d = valid.get(p)
        if d is None:
            continue
        for q in range(p - WINDOW, p + WINDOW + 1):
            if q != p and q in valid and valid[q] - d == q - p:
                anchors[p] = d
                break
    return anchors


def _monotonic(anchors: dict[int, int]) -> dict[int, int]:
    """Largest set of anchors whose printed numbers increase with the PDF page.

    A longest-increasing-subsequence is used (not a greedy scan) so that a pair of agreeing
    misreads (e.g. ৮৬৬/৮৬৭ instead of ২৬৬/২৬৭) cannot knock out the correct anchors after it.
    Also requires printed(b) - printed(a) <= pdf(b) - pdf(a): a printed number can never
    advance faster than the scan does (pages can be unnumbered, not duplicated).
    Numbering restarts (a new volume starting at 1) must be declared in page_mapping.json.
    """
    items = sorted(anchors.items())
    n = len(items)
    if n == 0:
        return {}
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        pi, di = items[i]
        for j in range(i):
            pj, dj = items[j]
            if dj < di and (di - dj) <= (pi - pj) and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j
    i = max(range(n), key=lambda k: best[k])
    kept: dict[int, int] = {}
    while i != -1:
        kept[items[i][0]] = items[i][1]
        i = prev[i]
    return kept


def infer_page_numbers(
    detected: dict[int, int | None],
    overrides: dict[int, int | str | None] | None = None,
) -> list[PageNumberResult]:
    overrides = overrides or {}
    anchors = _monotonic(_find_anchors(detected))
    results: dict[int, PageNumberResult] = {}
    pages = sorted(detected)

    for p in pages:
        if p in anchors:
            results[p] = PageNumberResult(p, detected[p], anchors[p], str(anchors[p]), "ocr")

    anchor_pages = sorted(anchors)
    for a, b in zip(anchor_pages, anchor_pages[1:]):
        gap_pages = [p for p in pages if a < p < b]
        if not gap_pages:
            continue
        da, db = anchors[a], anchors[b]
        numbers_available = db - da - 1
        if db > da and numbers_available == len(gap_pages):
            for k, p in enumerate(gap_pages, start=1):
                value = da + k
                src = "ocr" if detected.get(p) == value else "inferred"
                flag = "conflict" if detected.get(p) not in (None, value) else None
                results[p] = PageNumberResult(p, detected.get(p), value, str(value), src, flag)
        else:
            # Unnumbered plates/blank pages or missing scans: only accept detections that fit.
            for p in gap_pages:
                d = detected.get(p)
                if d is not None and da < d < db and (d - da) <= (p - a) and (db - d) <= (b - p):
                    results[p] = PageNumberResult(p, d, d, str(d), "ocr", "unverified")
                else:
                    results[p] = PageNumberResult(p, d, None, None, "unknown", "ambiguous_gap")

    # Before the first / after the last anchor: accept only self-consistent detections.
    if anchor_pages:
        first, last = anchor_pages[0], anchor_pages[-1]
        for p in pages:
            if p in results:
                continue
            d = detected.get(p)
            ref, ref_d = (first, anchors[first]) if p < first else (last, anchors[last])
            if d is not None and d - ref_d == p - ref:
                results[p] = PageNumberResult(p, d, d, str(d), "ocr", "unverified")
            else:
                results[p] = PageNumberResult(p, d, None, None, "unknown", "conflict" if d is not None else None)
    for p in pages:
        results.setdefault(p, PageNumberResult(p, detected.get(p), None, None, "unknown", None))

    # Manual overrides always win.
    for p, v in overrides.items():
        if p not in results:
            continue
        if v is None:
            results[p] = PageNumberResult(p, detected.get(p), None, None, "manual")
        elif isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            results[p] = PageNumberResult(p, detected.get(p), int(v), str(v), "manual")
        else:  # non-numeric label, e.g. roman numerals "iv"
            results[p] = PageNumberResult(p, detected.get(p), None, str(v), "manual")

    return [results[p] for p in pages]


def load_overrides(path: Path) -> dict[int, int | str | None]:
    """page_mapping.json format:

    {
      "pages":  {"263": 266, "5": null, "3": "iv"},
      "ranges": [{"pdf_start": 10, "pdf_end": 40, "printed_start": 13}]
    }
    Explicit "pages" entries win over "ranges".
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, int | str | None] = {}
    for r in data.get("ranges", []):
        for k, p in enumerate(range(int(r["pdf_start"]), int(r["pdf_end"]) + 1)):
            out[p] = int(r["printed_start"]) + k
    for k, v in data.get("pages", {}).items():
        out[int(k)] = v
    return out


def summarise(results: list[PageNumberResult]) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.source] = counts.get(r.source, 0) + 1
    flagged = [r.pdf_page for r in results if r.flag or r.source == "unknown"]
    return {"total": len(results), "by_source": counts, "needs_review": flagged}
