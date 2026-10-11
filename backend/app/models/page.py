from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Section(Base):
    """Hierarchical structure: level 1 = sub-book (e.g. ফাযায়েলে কুরআন), level 2 = chapter (পরিচ্ছেদ)."""

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    start_pdf_page: Mapped[int] = mapped_column(Integer)
    end_pdf_page: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual

    parent: Mapped[Section | None] = relationship(remote_side="Section.id")


class Page(Base):
    """One PDF page. `pdf_page_number` and `printed_page_number` are deliberately separate."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("book_id", "pdf_page_number", name="uq_pages_book_pdf_page"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    pdf_page_number: Mapped[int] = mapped_column(Integer)
    # Set when the scanner split ONE printed page into two narrow PDF pages (e.g. 189+190):
    # both rows point at the stitched image and this holds the partner PDF page number.
    merged_with_pdf_page: Mapped[int | None] = mapped_column(Integer)
    printed_page_number: Mapped[int | None] = mapped_column(Integer, index=True)
    printed_page_label: Mapped[str | None] = mapped_column(String(40))
    # manual | ocr | inferred | unknown  - how printed_page_number was established
    printed_page_source: Mapped[str] = mapped_column(String(20), default="unknown")
    detected_printed_page: Mapped[int | None] = mapped_column(Integer)  # raw OCR reading, for audit
    running_header: Mapped[str | None] = mapped_column(String(500))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"), index=True)
    image_path: Mapped[str | None] = mapped_column(String(500))  # object-storage key
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    ocr_engine: Mapped[str | None] = mapped_column(String(50))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    section: Mapped[Section | None] = relationship()
