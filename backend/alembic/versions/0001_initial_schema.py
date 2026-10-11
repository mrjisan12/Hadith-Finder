"""Initial schema: books, documents, sections, pages, paragraphs, chunks, embeddings, query_logs.

Revision ID: 0001
Revises:
Create Date: 2026-09-30

The embedding dimension is read from EMBEDDING_DIM at migration time. Changing the
embedding model to one with a different dimension requires a new migration.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "books",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("title_native", sa.String(300)),
        sa.Column("author", sa.String(300)),
        sa.Column("language", sa.String(20), nullable=False, server_default="bn"),
        sa.Column("description", sa.Text),
        sa.Column("total_pages", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_books_slug", "books", ["slug"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("storage_path", sa.String(500)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("ocr_engine", sa.String(50)),
        sa.Column("status", sa.String(30), nullable=False, server_default="registered"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_book_id", "documents", ["book_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("sections.id", ondelete="CASCADE")),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("start_pdf_page", sa.Integer, nullable=False),
        sa.Column("end_pdf_page", sa.Integer, nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="auto"),
    )
    op.create_index("ix_sections_book_id", "sections", ["book_id"])
    op.create_index("ix_sections_parent_id", "sections", ["parent_id"])

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pdf_page_number", sa.Integer, nullable=False),
        sa.Column("merged_with_pdf_page", sa.Integer),
        sa.Column("printed_page_number", sa.Integer),
        sa.Column("printed_page_label", sa.String(40)),
        sa.Column("printed_page_source", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("detected_printed_page", sa.Integer),
        sa.Column("running_header", sa.String(500)),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id", ondelete="SET NULL")),
        sa.Column("image_path", sa.String(500)),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("ocr_engine", sa.String(50)),
        sa.Column("ocr_confidence", sa.Float),
        sa.Column("ocr_text", sa.Text),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("book_id", "pdf_page_number", name="uq_pages_book_pdf_page"),
    )
    op.create_index("ix_pages_book_id", "pages", ["book_id"])
    op.create_index("ix_pages_document_id", "pages", ["document_id"])
    op.create_index("ix_pages_printed_page_number", "pages", ["printed_page_number"])
    op.create_index("ix_pages_section_id", "pages", ["section_id"])

    op.create_table(
        "paragraphs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.Integer, sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id", ondelete="SET NULL")),
        sa.Column("chapter_id", sa.Integer, sa.ForeignKey("sections.id", ondelete="SET NULL")),
        sa.Column("paragraph_index", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="text"),
        sa.Column("lang", sa.String(8), nullable=False, server_default="bn"),
        sa.Column("heading", sa.String(500)),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("bbox", postgresql.JSONB),
        sa.Column("line_boxes", postgresql.JSONB),
        sa.Column("continues_on_next_page", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("continued_from_prev_page", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("hadith_number", sa.String(20)),
        sa.Column("ocr_confidence", sa.Float),
        sa.UniqueConstraint("page_id", "paragraph_index", name="uq_paragraphs_page_index"),
    )
    op.create_index("ix_paragraphs_source_id", "paragraphs", ["source_id"], unique=True)
    op.create_index("ix_paragraphs_book_id", "paragraphs", ["book_id"])
    op.create_index("ix_paragraphs_page_id", "paragraphs", ["page_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.Integer, sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paragraph_id", sa.Integer, sa.ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("char_start", sa.Integer, nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embed_text", sa.Text, nullable=False),
        sa.Column("search_text", sa.Text, nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('simple', coalesce(search_text, ''))", persisted=True),
        ),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False, server_default="bn"),
        sa.UniqueConstraint("paragraph_id", "chunk_index", name="uq_chunks_paragraph_index"),
    )
    op.create_index("ix_chunks_source_id", "chunks", ["source_id"], unique=True)
    op.create_index("ix_chunks_book_id", "chunks", ["book_id"])
    op.create_index("ix_chunks_page_id", "chunks", ["page_id"])
    op.create_index("ix_chunks_paragraph_id", "chunks", ["paragraph_id"])
    op.create_index("ix_chunks_text_hash", "chunks", ["text_hash"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_search_trgm",
        "chunks",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("chunk_id", sa.Integer, sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chunk_id", "model", name="uq_embeddings_chunk_model"),
    )
    op.create_index("ix_embeddings_chunk_id", "embeddings", ["chunk_id"])
    op.create_index("ix_embeddings_model", "embeddings", ["model"])
    op.create_index(
        "ix_embeddings_hnsw",
        "embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 128},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "query_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("book_id", sa.Integer),
        sa.Column("understanding", postgresql.JSONB),
        sa.Column("candidate_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("selected_source_ids", postgresql.JSONB),
        sa.Column("cited_source_ids", postgresql.JSONB),
        sa.Column("insufficient_evidence", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("latencies_ms", postgresql.JSONB),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_query_logs_created_at", "query_logs", ["created_at"])


def downgrade() -> None:
    for table in ("query_logs", "embeddings", "chunks", "paragraphs", "pages", "sections", "documents", "books"):
        op.drop_table(table)
