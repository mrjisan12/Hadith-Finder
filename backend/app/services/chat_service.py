"""Chat orchestration: understand -> retrieve -> rerank -> generate -> verify citations.

Produces a stream of events (used for SSE) and a collector for the non-streaming endpoint.

Trust model: the LLM only receives passages and writes a short answer that cites passage ids.
Everything shown as a *source* is re-read from the database by id (app.citation.verify), and
citations are validated against the passages actually supplied for this request.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.citation.verify import sanitize_answer
from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import get_logger, log_event, timer
from app.generation.answer import message, split_insufficient, stream_answer
from app.generation.llm import LLMError
from app.models import QueryLog
from app.retrieval.hybrid import RetrievalResult, retrieve
from app.retrieval.query_understanding import understand_query
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.source import SourceOut

log = get_logger("chat")


def _final_sources(result: RetrievalResult | None, cited: list[str]) -> list[SourceOut]:
    if result is None:
        return []
    by_id = {s.source.source_id: s.source for s in result.selected}
    out: list[SourceOut] = []
    for rank, sid in enumerate(cited, start=1):
        if sid in by_id:
            out.append(by_id[sid].model_copy(update={"cited": True, "rank": rank}))
    for s in result.selected:
        if s.source.source_id not in cited:
            out.append(s.source.model_copy(update={"cited": False, "rank": len(out) + 1}))
    return out


def _save_log(**fields) -> int | None:
    try:
        with session_scope() as db:
            row = QueryLog(**fields)
            db.add(row)
            db.flush()
            return row.id
    except Exception as exc:  # observability must never break the request
        log.warning("could not write query log", extra={"fields": {"error": str(exc)[:200]}})
        return None


async def chat_events(req: ChatRequest) -> AsyncIterator[dict]:
    include_debug = req.debug and settings.enable_debug
    history = [t.model_dump() for t in req.history]
    latencies: dict[str, float] = {}
    result: RetrievalResult | None = None
    answer = ""
    insufficient = False
    cited: list[str] = []
    error: str | None = None

    with timer() as total:
        # 1. understand
        yield {"type": "status", "stage": "understanding"}
        with timer() as t:
            plan = await understand_query(req.query, history)
        latencies["understand"] = t()

        if not plan.in_scope:
            answer = message("out_of_scope", plan.language)
            yield {"type": "delta", "text": answer}
        else:
            # 2-3. retrieve + rerank
            yield {"type": "status", "stage": "retrieving"}
            with timer() as t:
                result = await retrieve(plan, req.book_id)
            latencies["retrieve"] = t()
            latencies.update({f"retrieve.{k}": v for k, v in result.latencies_ms.items()})

            if not result.selected:
                insufficient = True
                answer = message("insufficient", plan.language)
                yield {"type": "delta", "text": answer}
            else:
                # Verified sources can be shown before the answer is written.
                yield {"type": "sources", "sources": [s.source.model_dump() for s in result.selected]}
                yield {"type": "status", "stage": "generating"}
                parts: list[str] = []
                with timer() as t:
                    try:
                        async for delta in stream_answer(plan.original, plan.standalone_question, result.selected):
                            parts.append(delta)
                            yield {"type": "delta", "text": delta}
                    except LLMError as exc:
                        error = str(exc)
                        log.error("answer generation failed", extra={"fields": {"error": error}})
                latencies["generate"] = t()
                raw = "".join(parts)
                if error and not raw:
                    answer = message("llm_failed", plan.language)
                else:
                    allowed = {s.source.source_id for s in result.selected}
                    answer, cited, rejected = sanitize_answer(raw, allowed)
                    if rejected:
                        log.warning("dropped invalid citations", extra={"fields": {"rejected": rejected}})
                    insufficient, answer = split_insufficient(answer)
                    if insufficient:
                        cited = []
    latencies["total"] = total()

    sources = _final_sources(result, cited)
    selected_ids = [s.source.source_id for s in result.selected] if result else []
    query_id = await asyncio.to_thread(
        _save_log,
        query=req.query[:2000],
        book_id=req.book_id,
        understanding=plan.to_dict(),
        candidate_count=len(result.candidates) if result else 0,
        selected_source_ids=selected_ids,
        cited_source_ids=cited,
        insufficient_evidence=insufficient,
        latencies_ms=latencies,
        error=error,
    )
    log_event(
        log,
        "chat",
        query=req.query[:200],
        plan_source=plan.source,
        candidates=len(result.candidates) if result else 0,
        selected=selected_ids,
        cited=cited,
        insufficient=insufficient,
        latencies_ms=latencies,
        error=error,
    )
    final = {
        "type": "final",
        "answer": answer,
        "insufficient_evidence": insufficient,
        "sources": [s.model_dump() for s in sources],
        "query_id": query_id,
    }
    if error:
        final["error"] = "answer_generation_failed"
    if include_debug:
        final["debug"] = {"query_plan": plan.to_dict(), "latencies_ms": latencies, **(result.debug() if result else {})}
    yield final


async def chat_once(req: ChatRequest) -> ChatResponse:
    final: dict | None = None
    async for event in chat_events(req):
        if event["type"] == "final":
            final = event
    assert final is not None
    return ChatResponse(
        answer=final["answer"],
        insufficient_evidence=final["insufficient_evidence"],
        sources=[SourceOut(**s) for s in final["sources"]],
        query_id=final["query_id"],
        debug=final.get("debug"),
    )
