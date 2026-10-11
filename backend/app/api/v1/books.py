from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Book, Chunk, Page, Section
from app.schemas.book import BookDetailOut, BookOut, SectionOut

router = APIRouter(tags=["books"])


def _counts(db: Session) -> tuple[dict[int, int], dict[int, int]]:
    pages = dict(db.execute(select(Page.book_id, func.count()).group_by(Page.book_id)).all())
    chunks = dict(db.execute(select(Chunk.book_id, func.count()).group_by(Chunk.book_id)).all())
    return pages, chunks


def _book_out(book: Book, pages: dict, chunks: dict) -> dict:
    return dict(
        id=book.id,
        slug=book.slug,
        title=book.title,
        title_native=book.title_native,
        author=book.author,
        language=book.language,
        total_pages=book.total_pages,
        indexed_pages=pages.get(book.id, 0),
        indexed_chunks=chunks.get(book.id, 0),
    )


@router.get("/books", response_model=list[BookOut])
def list_books(db: Session = Depends(get_db)) -> list[BookOut]:
    pages, chunks = _counts(db)
    return [BookOut(**_book_out(b, pages, chunks)) for b in db.scalars(select(Book).order_by(Book.id))]


@router.get("/books/{book_id}", response_model=BookDetailOut)
def get_book(book_id: int, db: Session = Depends(get_db)) -> BookDetailOut:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    pages, chunks = _counts(db)
    sections = db.scalars(select(Section).where(Section.book_id == book_id).order_by(Section.start_pdf_page, Section.level))
    return BookDetailOut(
        **_book_out(book, pages, chunks),
        description=book.description,
        sections=[
            SectionOut(
                id=s.id,
                level=s.level,
                title=s.title,
                start_pdf_page=s.start_pdf_page,
                end_pdf_page=s.end_pdf_page,
                parent_id=s.parent_id,
            )
            for s in sections
        ],
    )
