"""Section structure from running headers.

Fazail-e-Amal is a compilation of sub-books (ফাযায়েলে তবলীগ, ফাযায়েলে কুরআন, হেকায়াতে সাহাবা,
ফাযায়েলে নামায, ফাযায়েলে যিকির, ফাযায়েলে রমযান, ...). The running header of each page names either
  * the sub-book  - "ফাযায়েলে কুরআন-৭৬"  (and in prefaces "হেকায়াতে সাহাবা-১২"), or
  * a chapter     - "দ্বিতীয় অধ্যায়-৯৯"  (inside sub-books organised in chapters).
So: non-chapter headers -> level 1 (sub-book); chapter headers -> level 2, nested under the most
recent sub-book. "প্রথম অধ্যায়" of two different sub-books therefore stay separate sections.
OCR noise in headers is absorbed by fuzzy clustering + a sliding majority vote. Chapter headings
detected inside the text are used only where a sub-book has no chapter headers.

Manual override: `sections.json` in the book config folder, e.g.
  [{"level": 1, "title": "ফাযায়েলে নামায", "start_pdf_page": 55, "end_pdf_page": 170}, ...]
If level-1 entries are given they replace the automatic sub-books (chapters from headers are kept
and re-parented); if level-2 entries are given they replace the automatic chapters.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from app.core.textnorm import fold_tokens
from ingestion.layout import PageLayout

SMOOTH_WINDOW = 3
CLUSTER_SIMILARITY = 85
_CHAPTER_HEADER = re.compile(r"অধ্যা[য়য]|পরিচ্ছেদ|অনুচ্ছেদ")


@dataclass
class SectionSpec:
    level: int
    title: str
    start_pdf_page: int
    end_pdf_page: int
    parent: int | None = None  # index into SectionPlan.sections
    source: str = "auto"


@dataclass
class SectionPlan:
    sections: list[SectionSpec] = field(default_factory=list)
    page_section: dict[int, int] = field(default_factory=dict)  # pdf_page -> level-1 section index
    para_chapter: dict[tuple[int, int], int] = field(default_factory=dict)  # (pdf_page, para_idx) -> level-2 idx
    para_heading: dict[tuple[int, int], str] = field(default_factory=dict)  # nearest heading text


def is_chapter_title(title: str) -> bool:
    return bool(_CHAPTER_HEADER.search(title))


def _key(title: str) -> str:
    return " ".join(fold_tokens(title, stem=False))


def _cluster_titles(titles: dict[int, str]) -> dict[int, str]:
    """Map each page's header title to a canonical title (most frequent spelling in its cluster)."""
    counts = Counter(_key(t) for t in titles.values() if _key(t))
    reps: list[str] = []
    key_to_rep: dict[str, str] = {}
    for key, _ in counts.most_common():
        match = next((r for r in reps if fuzz.ratio(key, r) >= CLUSTER_SIMILARITY), None)
        if match is None:
            reps.append(key)
            match = key
        key_to_rep[key] = match
    raw_by_rep: dict[str, Counter] = {}
    for t in titles.values():
        k = _key(t)
        if k:
            raw_by_rep.setdefault(key_to_rep[k], Counter())[t] += 1
    display = {rep: c.most_common(1)[0][0] for rep, c in raw_by_rep.items()}
    return {p: display[key_to_rep[_key(t)]] for p, t in titles.items() if _key(t)}


def _smooth(page_titles: dict[int, str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for p, own in page_titles.items():
        window = [page_titles[q] for q in range(p - SMOOTH_WINDOW, p + SMOOTH_WINDOW + 1) if q in page_titles]
        top, top_n = Counter(window).most_common(1)[0]
        out[p] = top if top_n > window.count(own) else own
    return out


def _fill_gaps(page_titles: dict[int, str], pages: list[int]) -> dict[int, str]:
    """Pages without a title join the NEXT one when they sit between two different titles
    (a title page precedes its book/chapter), else the surrounding one."""
    known = sorted(page_titles)
    if not known:
        return {}
    out = dict(page_titles)
    for p in pages:
        if p in out:
            continue
        before = [q for q in known if q < p]
        after = [q for q in known if q > p]
        if not before:
            out[p] = page_titles[after[0]]
        elif not after:
            out[p] = page_titles[before[-1]]
        else:
            a, b = page_titles[before[-1]], page_titles[after[0]]
            out[p] = a if a == b else b
    return out


def _runs(page_titles: dict[int, str | None], pages: list[int]) -> list[tuple[str, int, int]]:
    """Contiguous runs of the same title, as (title, first_page, last_page)."""
    runs: list[tuple[str, int, int]] = []
    prev_page: int | None = None
    for p in pages:
        t = page_titles.get(p)
        if t is not None:
            if runs and runs[-1][0] == t and runs[-1][2] == prev_page:
                runs[-1] = (t, runs[-1][1], p)
            else:
                runs.append((t, p, p))
        prev_page = p
    return runs


def build_sections(layouts: list[PageLayout], manual_path: Path | None = None) -> SectionPlan:
    layouts = sorted(layouts, key=lambda lay: lay.pdf_page)
    pages = [lay.pdf_page for lay in layouts]
    manual = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path and manual_path.exists() else []
    manual_l1 = [m for m in manual if int(m.get("level", 1)) == 1]
    manual_l2 = [m for m in manual if int(m.get("level", 1)) == 2]

    titles = _cluster_titles({lay.pdf_page: lay.header_title for lay in layouts if lay.header_title})
    book_titles = _smooth({p: t for p, t in titles.items() if not is_chapter_title(t)})
    chapter_titles = _smooth({p: t for p, t in titles.items() if is_chapter_title(t)})

    plan = SectionPlan()

    # ------------------------------------------------------------------ level 1 (sub-books)
    l1: dict[int, str] = {}
    if manual_l1:
        for m in manual_l1:
            for p in range(int(m["start_pdf_page"]), int(m["end_pdf_page"]) + 1):
                l1[p] = m["title"]
    else:
        l1 = dict(book_titles)
        last = None
        for p in pages:  # chapter-header pages belong to the sub-book whose preface came before
            if p in l1:
                last = l1[p]
            elif p in chapter_titles and last is not None:
                l1[p] = last
        l1 = _fill_gaps(l1, pages)
    for title, start, end in _runs(l1, pages):
        plan.sections.append(SectionSpec(1, title, start, end, source="manual" if manual_l1 else "auto"))
        for p in pages:
            if start <= p <= end:
                plan.page_section[p] = len(plan.sections) - 1

    # ------------------------------------------------------------------ level 2 (chapters)
    page_chapter: dict[int, int] = {}
    if manual_l2:
        for m in manual_l2:
            start, end = int(m["start_pdf_page"]), int(m["end_pdf_page"])
            idx = len(plan.sections)
            plan.sections.append(SectionSpec(2, m["title"], start, end, plan.page_section.get(start), "manual"))
            for p in pages:
                if start <= p <= end:
                    page_chapter[p] = idx
    else:
        # Fill chapter gaps only inside the same sub-book.
        for sec_idx, spec in enumerate(list(plan.sections)):
            sec_pages = [p for p in pages if plan.page_section.get(p) == sec_idx]
            local = {p: chapter_titles[p] for p in sec_pages if p in chapter_titles}
            if not local:
                continue
            first = min(local)
            filled = _fill_gaps(local, [p for p in sec_pages if p >= first])  # preface stays chapter-less
            for title, start, end in _runs(filled, sec_pages):
                idx = len(plan.sections)
                plan.sections.append(SectionSpec(2, title, start, end, sec_idx))
                for p in sec_pages:
                    if start <= p <= end:
                        page_chapter[p] = idx

    # ------------------------------------------------------------------ paragraphs: chapter + heading
    header_chapter_sections = {plan.page_section.get(p) for p in page_chapter}
    text_chapter: int | None = None
    heading: str | None = None
    prev_section: int | None = None
    for lay in layouts:
        sec = plan.page_section.get(lay.pdf_page)
        if sec != prev_section:
            text_chapter, heading, prev_section = None, None, sec
        use_text_chapters = not manual_l2 and sec not in header_chapter_sections
        for para in lay.paragraphs:
            if para.kind == "heading":
                heading = para.text
                if para.is_chapter_heading and use_text_chapters:
                    text_chapter = len(plan.sections)
                    plan.sections.append(SectionSpec(2, para.text, lay.pdf_page, lay.pdf_page, sec))
            chapter = page_chapter.get(lay.pdf_page) if not use_text_chapters else text_chapter
            if chapter is not None:
                plan.para_chapter[(lay.pdf_page, para.index)] = chapter
                if use_text_chapters:
                    plan.sections[chapter].end_pdf_page = lay.pdf_page
            if heading:
                plan.para_heading[(lay.pdf_page, para.index)] = heading
    return plan
