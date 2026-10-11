from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.database import Base
from app.models.page import Page, Section

EMBEDDING_DIM = get_settings().embedding_dim


class Paragraph(Base):
    """An original paragraph exactly as OCR'd from one page, in reading order.

    This is the text shown to users as the "Original Source" - it is never produced by the LLM.
    """

    __tablename__ = "paragraphs"
    __table_args__ = (UniqueConstraint("page_id", "paragraph_index", name="uq_paragraphs_page_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # para_xxxxxxxxxx
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    paragraph_index: Mapped[int] = mapped_column(Integer)  # order on the page, 0-based
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text | heading
    lang: Mapped[str] = mapped_column(String(8), default="bn")  # bn | ar | ur | en
    heading: Mapped[str | None] = mapped_column(String(500))  # nearest preceding heading
    text: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list | None] = mapped_column(JSONB)  # [x0,y0,x1,y1] normalised 0..1
    line_boxes: Mapped[list | None] = mapped_column(JSONB)  # [[x0,y0,x1,y1], ...] normalised
    continues_on_next_page: Mapped[bool] = mapped_column(Boolean, default=False)
    continued_from_prev_page: Mapped[bool] = mapped_column(Boolean, default=False)
    hadith_number: Mapped[str | None] = mapped_column(String(20))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)

    page: Mapped[Page] = relationship()
    section: Mapped[Section | None] = relationship(foreign_keys=[section_id])
    chapter: Mapped[Section | None] = relationship(foreign_keys=[chapter_id])


class Chunk(Base):
    """Retrieval unit. Usually 1:1 with a paragraph; long paragraphs are split (char_start/char_end)."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("paragraph_id", "chunk_index", name="uq_chunks_paragraph_index"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # chunk_xxxxxxxxxx
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("paragraphs.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)  # exact slice of paragraph.text
    embed_text: Mapped[str] = mapped_column(Text)  # text + context used for the embedding
    search_text: Mapped[str] = mapped_column(Text)  # folded ASCII search key (see app.core.textnorm)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', coalesce(search_text, ''))", persisted=True))
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    lang: Mapped[str] = mapped_column(String(8), default="bn")

    paragraph: Mapped[Paragraph] = relationship()
    page: Mapped[Page] = relationship()


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model", name="uq_embeddings_chunk_model"),
        Index(
            "ix_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 128},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    text_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunk: Mapped[Chunk] = relationship()


class QueryLog(Base):
    """Per-request observability record (no secrets, no raw API responses)."""

    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    query: Mapped[str] = mapped_column(Text)
    book_id: Mapped[int | None] = mapped_column(Integer)
    understanding: Mapped[dict | None] = mapped_column(JSONB)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    selected_source_ids: Mapped[list | None] = mapped_column(JSONB)
    cited_source_ids: Mapped[list | None] = mapped_column(JSONB)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    latencies_ms: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
