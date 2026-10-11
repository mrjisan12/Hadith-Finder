from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.citation.verify import page_image_url
from app.core.database import get_db
from app.models import Book, Page, Paragraph, Section
from app.schemas.book import PageOut, ParagraphBox
from app.services.storage import get_storage

router = APIRouter(tags=["pages"])


@router.get("/pages/{page_id}", response_model=PageOut, summary="Page metadata incl. paragraph boxes for highlighting")
def get_page(page_id: int, db: Session = Depends(get_db)) -> PageOut:
    page = db.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    book = db.get(Book, page.book_id)
    section = db.get(Section, page.section_id) if page.section_id else None
    neighbours = dict(
        db.execute(
            select(Page.pdf_page_number, Page.id).where(
                Page.book_id == page.book_id,
                Page.pdf_page_number.in_([page.pdf_page_number - 1, page.pdf_page_number + 1]),
            )
        ).all()
    )
    paragraphs = db.scalars(select(Paragraph).where(Paragraph.page_id == page.id).order_by(Paragraph.paragraph_index))
    return PageOut(
        id=page.id,
        book_id=page.book_id,
        book=book.title,
        book_native=book.title_native,
        pdf_page=page.pdf_page_number,
        merged_with_pdf_page=page.merged_with_pdf_page,
        printed_page=page.printed_page_number,
        printed_page_label=page.printed_page_label,
        printed_page_source=page.printed_page_source,
        section=section.title if section else None,
        running_header=page.running_header,
        image_url=page_image_url(page.id),
        width=page.width,
        height=page.height,
        needs_review=page.needs_review,
        prev_page_id=neighbours.get(page.pdf_page_number - 1),
        next_page_id=neighbours.get(page.pdf_page_number + 1),
        paragraphs=[
            ParagraphBox(
                paragraph_id=p.source_id,
                paragraph_index=p.paragraph_index,
                kind=p.kind,
                lang=p.lang,
                bbox=p.bbox,
                line_boxes=p.line_boxes,
            )
            for p in paragraphs
        ],
    )


@router.get("/pages/{page_id}/image", summary="The original scanned page image", response_class=FileResponse)
def get_page_image(page_id: int, db: Session = Depends(get_db)):
    image_path = db.scalar(select(Page.image_path).where(Page.id == page_id))
    if not image_path:
        raise HTTPException(status_code=404, detail="Page not found")
    storage = get_storage()
    if storage.name == "local":
        path = storage.local_path(image_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Page image not found; run the ingestion render stage")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    url = storage.public_url(image_path)
    if not url:
        raise HTTPException(status_code=404, detail="Page image not available")
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, max-age=300"})
