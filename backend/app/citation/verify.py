"""Citation verification - the anti-hallucination boundary.

1. `load_sources` builds source objects exclusively from database rows (chunk -> paragraph ->
   page -> book/section). This is the only place `original_text` comes from.
2. `extract_citations` finds source ids cited by the LLM.
3. `sanitize_answer` removes any cited id that was not among the passages actually given to the
   LLM for this request (or that doesn't exist), so the UI can never show a fabricated citation.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models import Book, Chunk, Page, Paragraph, Section
from app.schemas.source import PagePart, SourceOut

CHUNK_ID_RE = re.compile(r"chunk_[0-9a-f]{10}")
_BRACKET_GROUP = re.compile(r"\[([^\[\]\n]{0,300}?)\]")


def page_image_url(page_id: int) -> str:
    return f"/api/v1/pages/{page_id}/image"


def pdf_page_end(page: Page) -> int | None:
    """Last PDF page of a printed page that the scanner split over two PDF pages."""
    m = page.merged_with_pdf_page
    return m if m is not None and m > page.pdf_page_number else None


def _page_part(db: Session, page: Page, paragraph: Paragraph) -> PagePart:
    return PagePart(
        text=paragraph.text,
        page_id=page.id,
        pdf_page=page.pdf_page_number,
        pdf_page_end=pdf_page_end(page),
        printed_page=page.printed_page_number,
        printed_page_label=page.printed_page_label,
        page_image_url=page_image_url(page.id),
    )


def _neighbour_part(db: Session, page: Page, direction: int) -> PagePart | None:
    """First paragraph of the next page (direction=+1) or last text paragraph of the previous page (-1)."""
    target = page.pdf_page_number + direction
    if page.merged_with_pdf_page == target:  # step over my own split-page partner
        target += direction
    other = db.scalar(select(Page).where(Page.book_id == page.book_id, Page.pdf_page_number == target))
    if other is not None and other.merged_with_pdf_page is not None and other.merged_with_pdf_page < other.pdf_page_number:
        # Stepping back onto the (text-less) second strip of a split page: its text is on the first strip.
        other = db.scalar(
            select(Page).where(Page.book_id == page.book_id, Page.pdf_page_number == other.merged_with_pdf_page)
        )
    if other is None:
        return None
    q = select(Paragraph).where(Paragraph.page_id == other.id, Paragraph.kind == "text")
    q = q.order_by(Paragraph.paragraph_index if direction > 0 else Paragraph.paragraph_index.desc()).limit(1)
    para = db.scalar(q)
    if para is None:
        return None
    if direction > 0 and not para.continued_from_prev_page:
        return None
    if direction < 0 and not para.continues_on_next_page:
        return None
    return _page_part(db, other, para)


def load_sources(db: Session, source_ids: list[str]) -> dict[str, SourceOut]:
    """Fetch verified source objects for chunk source ids. Unknown ids are simply absent."""
    ids = [s for s in dict.fromkeys(source_ids) if CHUNK_ID_RE.fullmatch(s)]
    if not ids:
        return {}
    SectionL1 = aliased(Section)
    Chapter = aliased(Section)
    rows = db.execute(
        select(Chunk, Paragraph, Page, Book, SectionL1.title, Chapter.title)
        .join(Paragraph, Paragraph.id == Chunk.paragraph_id)
        .join(Page, Page.id == Chunk.page_id)
        .join(Book, Book.id == Chunk.book_id)
        .outerjoin(SectionL1, SectionL1.id == Paragraph.section_id)
        .outerjoin(Chapter, Chapter.id == Paragraph.chapter_id)
        .where(Chunk.source_id.in_(ids))
    ).all()
    out: dict[str, SourceOut] = {}
    for chunk, para, page, book, section_title, chapter_title in rows:
        out[chunk.source_id] = SourceOut(
            source_id=chunk.source_id,
            paragraph_id=para.source_id,
            book_id=book.id,
            book=book.title,
            book_native=book.title_native,
            section=section_title,
            chapter=chapter_title,
            heading=para.heading,
            page_id=page.id,
            pdf_page=page.pdf_page_number,
            pdf_page_end=pdf_page_end(page),
            printed_page=page.printed_page_number,
            printed_page_label=page.printed_page_label,
            printed_page_source=page.printed_page_source,
            original_text=para.text,
            matched_text=chunk.text,
            match_start=chunk.char_start,
            match_end=chunk.char_end,
            lang=para.lang,
            hadith_number=para.hadith_number,
            ocr_confidence=para.ocr_confidence,
            bbox=para.bbox,
            line_boxes=para.line_boxes,
            continuation=_neighbour_part(db, page, +1) if para.continues_on_next_page else None,
            previous_part=_neighbour_part(db, page, -1) if para.continued_from_prev_page else None,
            page_image_url=page_image_url(page.id),
        )
    return out


def extract_citations(answer: str) -> list[str]:
    """All chunk ids cited inside square brackets, in order of first appearance."""
    seen: dict[str, None] = {}
    for group in _BRACKET_GROUP.findall(answer):
        for cid in CHUNK_ID_RE.findall(group):
            seen.setdefault(cid, None)
    return list(seen)


def sanitize_answer(answer: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    """Normalise citation groups to `[id][id]`, dropping ids not in `allowed`.

    Returns (clean_answer, valid_ids_in_order, rejected_ids).
    """
    valid: dict[str, None] = {}
    rejected: dict[str, None] = {}

    def repl(m: re.Match) -> str:
        ids = CHUNK_ID_RE.findall(m.group(1))
        if not ids:
            return m.group(0)  # an ordinary bracket, not a citation
        keep = []
        for cid in ids:
            if cid in allowed:
                keep.append(cid)
                valid.setdefault(cid, None)
            else:
                rejected.setdefault(cid, None)
        return "".join(f"[{cid}]" for cid in keep)

    clean = _BRACKET_GROUP.sub(repl, answer)

    def bare(m: re.Match) -> str:  # ids written without brackets
        cid = m.group(0)
        if cid in allowed:
            valid.setdefault(cid, None)
            return f"[{cid}]"
        rejected.setdefault(cid, None)
        return ""

    clean = re.sub(r"(?<!\[)chunk_[0-9a-f]{10}(?!\])", bare, clean)
    clean = re.sub(r"[ \t]+([।.,;:!?])", r"\1", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return clean, extract_citations(clean), list(rejected)
