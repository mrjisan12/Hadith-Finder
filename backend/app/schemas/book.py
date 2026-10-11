from __future__ import annotations

from pydantic import BaseModel


class SectionOut(BaseModel):
    id: int
    level: int
    title: str
    start_pdf_page: int
    end_pdf_page: int
    parent_id: int | None


class BookOut(BaseModel):
    id: int
    slug: str
    title: str
    title_native: str | None
    author: str | None
    language: str
    total_pages: int | None
    indexed_pages: int = 0
    indexed_chunks: int = 0


class BookDetailOut(BookOut):
    description: str | None
    sections: list[SectionOut]


class ParagraphBox(BaseModel):
    paragraph_id: str
    paragraph_index: int
    kind: str
    lang: str
    bbox: list[float] | None
    line_boxes: list[list[float]] | None


class PageOut(BaseModel):
    id: int
    book_id: int
    book: str
    book_native: str | None
    pdf_page: int
    merged_with_pdf_page: int | None
    printed_page: int | None
    printed_page_label: str | None
    printed_page_source: str
    section: str | None
    running_header: str | None
    image_url: str
    width: int | None
    height: int | None
    needs_review: bool
    prev_page_id: int | None
    next_page_id: int | None
    paragraphs: list[ParagraphBox]
