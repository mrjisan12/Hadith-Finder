"""Development-only endpoints to inspect why passages were (not) selected.
Registered only when ENABLE_DEBUG=true."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.core.config import settings
from app.core.security import limiter
from app.retrieval.hybrid import retrieve
from app.retrieval.query_understanding import fallback_plan, understand_query

router = APIRouter(tags=["debug"], prefix="/debug")


@router.get("/retrieve", summary="Run retrieval (no answer generation) and return every candidate with scores")
@limiter.limit(settings.rate_limit_chat)
async def debug_retrieve(
    request: Request,
    q: str = Query(min_length=1, max_length=1000),
    book_id: int | None = None,
    understand: bool = True,
    rerank: bool = True,
) -> dict:
    plan = await understand_query(q, []) if understand else fallback_plan(q)
    result = await retrieve(plan, book_id, use_reranker=rerank)
    return {
        "query_plan": plan.to_dict(),
        **result.debug(),
        "selected": [s.source.model_dump(exclude={"line_boxes", "bbox"}) for s in result.selected],
    }


@router.get("/config", summary="Effective configuration (secrets redacted)")
def debug_config() -> dict:
    return settings.safe_dict()
