from __future__ import annotations

from pydantic import BaseModel, Field


class PagePart(BaseModel):
    """The part of a paragraph that sits on a neighbouring page (paragraph split by a page break)."""

    text: str
    page_id: int
    pdf_page: int
    pdf_page_end: int | None = None  # set when one printed page spans two PDF pages
    printed_page: int | None
    printed_page_label: str | None
    page_image_url: str


class SourceOut(BaseModel):
    """A verified source. Every text field here is read from the database - never from the LLM."""

    source_id: str = Field(description="Stable chunk ID, e.g. chunk_8f72a1c9d0")
    paragraph_id: str
    book_id: int
    book: str
    book_native: str | None
    section: str | None = None
    chapter: str | None = None
    heading: str | None = None
    page_id: int
    pdf_page: int
    pdf_page_end: int | None = Field(default=None, description="Set when one printed page spans two PDF pages")
    printed_page: int | None
    printed_page_label: str | None
    printed_page_source: str = Field(description="manual | ocr | inferred | unknown")
    original_text: str = Field(description="Exact original paragraph (OCR of the scan)")
    matched_text: str = Field(description="The retrieved chunk inside original_text")
    match_start: int
    match_end: int
    lang: str
    hadith_number: str | None = None
    ocr_confidence: float | None = None
    bbox: list[float] | None = None
    line_boxes: list[list[float]] | None = None
    continuation: PagePart | None = None
    previous_part: PagePart | None = None
    page_image_url: str
    relevance_score: float | None = None
    cited: bool = False
    rank: int = 0
