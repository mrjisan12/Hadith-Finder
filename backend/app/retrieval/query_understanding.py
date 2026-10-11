"""LLM query understanding: standalone question, Bangla paraphrases in the book's style,
spelling-variant keywords and a hypothetical passage (HyDE) for vector search.

Everything produced here is used ONLY to search. None of it is shown as source text.
Failure is non-fatal: retrieval falls back to the raw question.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from cachetools import TTLCache

from app.core.config import settings
from app.core.logging import get_logger
from app.core.textnorm import detect_script
from app.generation.llm import LLMError, get_llm
from app.generation.prompts import (
    QUERY_UNDERSTANDING_SCHEMA,
    QUERY_UNDERSTANDING_SYSTEM,
    query_understanding_prompt,
)

log = get_logger("query_understanding")
_cache: TTLCache = TTLCache(maxsize=512, ttl=3600)


@dataclass
class QueryPlan:
    original: str
    standalone_question: str
    language: str
    in_scope: bool = True
    search_queries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    hypothetical_passage: str = ""
    source: str = "llm"  # llm | fallback

    def to_dict(self) -> dict:
        return asdict(self)


def fallback_plan(query: str) -> QueryPlan:
    lang = detect_script(query)
    return QueryPlan(
        original=query,
        standalone_question=query,
        language=lang if lang in ("bn", "en", "ar", "ur") else "other",
        source="fallback",
    )


async def understand_query(query: str, history: list[dict]) -> QueryPlan:
    if not settings.enable_query_understanding:
        return fallback_plan(query)
    key = hashlib.sha256(json.dumps([query, history[-6:]], ensure_ascii=False).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        data = await get_llm().complete_json(
            system=QUERY_UNDERSTANDING_SYSTEM,
            prompt=query_understanding_prompt(query, history),
            schema=QUERY_UNDERSTANDING_SCHEMA,
            max_tokens=4000,
        )
    except LLMError as exc:
        log.warning("query understanding failed; using raw query", extra={"fields": {"error": str(exc)}})
        return fallback_plan(query)

    plan = QueryPlan(
        original=query,
        standalone_question=(data.get("standalone_question") or query).strip()[:1000],
        language=data.get("language") or "bn",
        in_scope=bool(data.get("in_scope", True)),
        search_queries=[q.strip()[:300] for q in data.get("search_queries", []) if q and q.strip()][:4],
        keywords=[k.strip()[:60] for k in data.get("keywords", []) if k and k.strip()][:15],
        hypothetical_passage=(data.get("hypothetical_passage") or "").strip()[:1200],
    )
    _cache[key] = plan
    return plan
