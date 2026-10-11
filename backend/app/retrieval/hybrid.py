"""Hybrid retrieval: (LLM query plan) -> vector + full-text + trigram -> RRF -> rerank -> top-k.

The unit returned is a *paragraph* (identified by its best-matching chunk's source id), so the
answer model and the user both see complete original paragraphs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.citation.verify import load_sources
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger, timer
from app.core.textnorm import fold_tokens, query_terms
from app.embeddings.base import embed_queries, get_embedding_provider
from app.models import Chunk
from app.reranking.base import RerankItem, get_reranker, min_score, rerank
from app.retrieval.fusion import Candidate, rrf_fuse
from app.retrieval.query_understanding import QueryPlan
from app.retrieval.search import Hit, fulltext_search, trigram_search, vector_search
from app.schemas.source import SourceOut

log = get_logger("retrieval")

PREV_CONTEXT_CHARS = 600
NEXT_CONTEXT_CHARS = 900


@dataclass
class Selected:
    source: SourceOut
    candidate: Candidate
    context_text: str  # full paragraph (+ page-break neighbours) given to the answer model


@dataclass
class RetrievalResult:
    selected: list[Selected]
    candidates: list[Candidate]
    sources_by_id: dict[str, SourceOut]
    reranker: str
    threshold: float
    latencies_ms: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    list_sizes: dict[str, int] = field(default_factory=dict)

    def debug(self) -> dict:
        selected_ids = {s.source.source_id for s in self.selected}
        rows = []
        for c in self.candidates:
            src = self.sources_by_id.get(c.source_id) if c.source_id else None
            rows.append(
                {
                    "source_id": c.source_id,
                    "pdf_page": src.pdf_page if src else None,
                    "printed_page": src.printed_page_label if src else None,
                    "section": src.section if src else None,
                    "fused_score": round(c.fused_score, 5),
                    "rerank_score": c.rerank_score,
                    "ranks": c.ranks,
                    "raw_scores": c.raw_scores,
                    "selected": c.source_id in selected_ids,
                    "snippet": (src.matched_text[:180] + "…") if src else None,
                }
            )
        return {
            "reranker": self.reranker,
            "threshold": self.threshold,
            "list_sizes": self.list_sizes,
            "latencies_ms": self.latencies_ms,
            "errors": self.errors,
            "candidates": rows,
        }


def _vector_texts(plan: QueryPlan) -> dict[str, str]:
    texts: dict[str, str] = {"vec_question": plan.standalone_question}
    if plan.original.strip() != plan.standalone_question.strip():
        texts["vec_original"] = plan.original
    for i, q in enumerate(plan.search_queries[:3]):
        texts[f"vec_q{i + 1}"] = q
    if plan.hypothetical_passage:
        texts["vec_hyde"] = plan.hypothetical_passage
    # drop exact duplicates
    seen, out = set(), {}
    for k, v in texts.items():
        if v and v not in seen:
            seen.add(v)
            out[k] = v
    return out


def _keyword_terms(plan: QueryPlan) -> tuple[list[str], list[str]]:
    fts: dict[str, None] = {}
    for text in [plan.original, plan.standalone_question, *plan.search_queries]:
        for t in query_terms(text):
            fts.setdefault(t, None)
    kw_terms: dict[str, None] = {}
    for kw in plan.keywords:
        for t in fold_tokens(kw):
            kw_terms.setdefault(t, None)
            fts.setdefault(t, None)
    trigram = list(kw_terms) + [t for t in query_terms(plan.original) if t not in kw_terms]
    return list(fts)[:30], trigram


WEIGHTS = {
    "vec_question": 1.0,
    "vec_original": 1.0,
    "vec_q1": 0.8,
    "vec_q2": 0.8,
    "vec_q3": 0.8,
    "vec_hyde": 0.8,
    "fts": 1.0,
    "trigram": 0.6,
}


def _run_searches(vectors: dict[str, list[float]], model_key: str, fts_terms, trgm_terms, book_id) -> dict[str, list[Hit]]:
    k_vec, k_kw = settings.retrieval_vector_k, settings.retrieval_keyword_k
    lists: dict[str, list[Hit]] = {}
    db = SessionLocal()
    try:
        for name, vec in vectors.items():
            lists[name] = vector_search(db, vec, model_key, k_vec, book_id)
        lists["fts"] = fulltext_search(db, fts_terms, k_kw, book_id)
        lists["trigram"] = trigram_search(db, trgm_terms, k_kw, book_id)
        db.rollback()
    finally:
        db.close()
    return lists


def _load_candidate_sources(chunk_ids: list[int]) -> tuple[dict[int, str], dict[str, SourceOut]]:
    db = SessionLocal()
    try:
        from sqlalchemy import select

        rows = db.execute(select(Chunk.id, Chunk.source_id).where(Chunk.id.in_(chunk_ids))).all()
        id_map = {r.id: r.source_id for r in rows}
        return id_map, load_sources(db, list(id_map.values()))
    finally:
        db.close()


def _context_text(src: SourceOut) -> str:
    parts = []
    if src.previous_part:
        parts.append("…" + src.previous_part.text[-PREV_CONTEXT_CHARS:])
    parts.append(src.original_text)
    if src.continuation:
        parts.append(src.continuation.text[:NEXT_CONTEXT_CHARS] + "…")
    return "\n".join(parts)


def _rerank_text(src: SourceOut) -> str:
    path = " › ".join(x for x in (src.section, src.chapter, src.heading) if x)
    return (f"[{path}]\n" if path else "") + _context_text(src)


async def retrieve(plan: QueryPlan, book_id: int | None = None, use_reranker: bool = True) -> RetrievalResult:
    latencies: dict[str, float] = {}
    errors: list[str] = []

    # 1. embed query variants (one batched call)
    vec_texts = _vector_texts(plan)
    vectors: dict[str, list[float]] = {}
    model_key = ""
    with timer() as t:
        try:
            provider = get_embedding_provider()
            model_key = f"{provider.model}@{provider.dim}"
            embedded = await embed_queries(list(vec_texts.values()))
            vectors = dict(zip(vec_texts.keys(), embedded))
        except Exception as exc:  # keyword search still works without embeddings
            errors.append(f"embedding failed: {type(exc).__name__}: {str(exc)[:160]}")
            log.error("query embedding failed", extra={"fields": {"error": str(exc)[:200]}})
    latencies["embed"] = t()

    # 2. run all retrievers
    fts_terms, trgm_terms = _keyword_terms(plan)
    with timer() as t:
        lists = await asyncio.to_thread(_run_searches, vectors, model_key, fts_terms, trgm_terms, book_id)
    latencies["search"] = t()

    # 3. fuse
    fused = rrf_fuse(lists, WEIGHTS)
    pool = fused[: settings.retrieval_rerank_candidates * 2]
    id_map, sources = await asyncio.to_thread(_load_candidate_sources, [c.chunk_id for c in pool])

    # one candidate per paragraph (best fused chunk wins)
    seen_paragraphs: set[str] = set()
    candidates: list[Candidate] = []
    for c in pool:
        sid = id_map.get(c.chunk_id)
        src = sources.get(sid) if sid else None
        if src is None or src.paragraph_id in seen_paragraphs:
            continue
        seen_paragraphs.add(src.paragraph_id)
        c.source_id = sid
        candidates.append(c)
        if len(candidates) >= settings.retrieval_rerank_candidates:
            break

    # 4. rerank
    reranker = get_reranker()
    threshold = min_score(reranker) if use_reranker else 0.0
    used = "disabled"
    with timer() as t:
        if candidates and use_reranker:
            items = [RerankItem(key=c.source_id, text=_rerank_text(sources[c.source_id])) for c in candidates]
            scores, used = await rerank(plan.standalone_question, plan.original, items)
            if used != reranker.name:
                threshold = 0.0
            for c in candidates:
                c.rerank_score = round(scores.get(c.source_id, 0.0), 4)
            candidates.sort(key=lambda c: (-(c.rerank_score or 0.0), -c.fused_score))
    latencies["rerank"] = t()

    # 5. select
    selected: list[Selected] = []
    for c in candidates:
        if len(selected) >= settings.retrieval_top_k:
            break
        score = c.rerank_score if c.rerank_score is not None else 1.0
        if score < threshold:
            continue
        src = sources[c.source_id].model_copy(update={"relevance_score": c.rerank_score, "rank": len(selected) + 1})
        selected.append(Selected(source=src, candidate=c, context_text=_context_text(src)))

    return RetrievalResult(
        selected=selected,
        candidates=candidates,
        sources_by_id=sources,
        reranker=used,
        threshold=threshold,
        latencies_ms=latencies,
        errors=errors,
        list_sizes={k: len(v) for k, v in lists.items()},
    )
