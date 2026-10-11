"""Retrievers: pgvector similarity, PostgreSQL full-text, and trigram fuzzy matching.

All SQL is parameterised (no string interpolation of user input). Keyword search runs on
`chunks.search_text`, the folded ASCII key built by app.core.textnorm.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from app.core.config import settings
from app.core.textnorm import to_tsquery_expr
from app.models import Chunk, Embedding


@dataclass
class Hit:
    chunk_id: int
    score: float


def vector_search(db: Session, vector: list[float], model_key: str, k: int, book_id: int | None) -> list[Hit]:
    if settings.vector_search_mode == "exact":
        # Exact scan: 100% recall. A book has ~10-20k chunks, so this stays in the tens of ms.
        db.execute(text("SET LOCAL enable_indexscan = off"))
    else:
        db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    dist = Embedding.embedding.cosine_distance(vector).label("dist")
    stmt = select(Embedding.chunk_id, dist).where(Embedding.model == model_key)
    if book_id is not None:
        stmt = stmt.join(Chunk, Chunk.id == Embedding.chunk_id).where(Chunk.book_id == book_id)
    rows = db.execute(stmt.order_by(dist).limit(k)).all()
    db.execute(text("RESET enable_indexscan"))
    return [Hit(chunk_id=r.chunk_id, score=1.0 - float(r.dist)) for r in rows]


_FTS_SQL = text(
    """
    SELECT c.id AS chunk_id, ts_rank_cd(c.tsv, q, 1) AS score
    FROM chunks c, to_tsquery('simple', :tsq) AS q
    WHERE c.tsv @@ q AND (CAST(:book_id AS integer) IS NULL OR c.book_id = :book_id)
    ORDER BY score DESC, c.id
    LIMIT :k
    """
)


def fulltext_search(db: Session, terms: list[str], k: int, book_id: int | None) -> list[Hit]:
    tsq = to_tsquery_expr(terms)
    if not tsq:
        return []
    rows = db.execute(_FTS_SQL, {"tsq": tsq, "k": k, "book_id": book_id}).all()
    return [Hit(chunk_id=r.chunk_id, score=float(r.score)) for r in rows]


_TRGM_SQL = text(
    """
    SELECT c.id AS chunk_id,
           count(*) AS hits,
           sum(word_similarity(t, c.search_text)) AS score
    FROM unnest(:terms) AS t
    JOIN chunks c ON t <% c.search_text
    WHERE (CAST(:book_id AS integer) IS NULL OR c.book_id = :book_id)
    GROUP BY c.id
    ORDER BY hits DESC, score DESC, c.id
    LIMIT :k
    """
).bindparams(bindparam("terms", type_=ARRAY(Text)))


def trigram_search(db: Session, terms: list[str], k: int, book_id: int | None, threshold: float = 0.6) -> list[Hit]:
    """Fuzzy term matching - catches OCR errors and spelling variants the folding misses."""
    terms = [t for t in dict.fromkeys(terms) if len(t) >= 4][:10]
    if not terms:
        return []
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"), {"t": str(threshold)})
    rows = db.execute(_TRGM_SQL, {"terms": terms, "k": k, "book_id": book_id}).all()
    return [Hit(chunk_id=r.chunk_id, score=float(r.score)) for r in rows]
