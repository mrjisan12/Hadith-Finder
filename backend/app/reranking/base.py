"""Rerankers. Swap with RERANKER_PROVIDER:

* llm    - listwise relevance scoring with the configured LLM (default; strong on Bangla and
           needs no extra API key)
* cohere - Cohere rerank-v3.5 (multilingual)
* jina   - Jina jina-reranker-v2-base-multilingual
* none   - keep the fusion order (fallback; no relevance threshold is possible)

Every reranker returns a score normalised to 0..1 per passage.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.generation.llm import LLMError, get_llm
from app.generation.prompts import RERANK_SCHEMA, RERANK_SYSTEM, rerank_prompt

log = get_logger("rerank")

MAX_PASSAGE_CHARS = 1600


@dataclass
class RerankItem:
    key: str  # opaque id (chunk source_id)
    text: str


class Reranker(Protocol):
    name: str
    default_min_score: float

    async def score(self, question: str, original: str, items: list[RerankItem]) -> dict[str, float]: ...


class NoReranker:
    name = "none"
    default_min_score = 0.0

    async def score(self, question, original, items):
        n = len(items)
        return {it.key: 1.0 - i / max(n, 1) for i, it in enumerate(items)}


class LLMReranker:
    name = "llm"
    default_min_score = 0.5  # score >= 5/10

    async def score(self, question, original, items):
        aliases = {f"p{i + 1}": it for i, it in enumerate(items)}
        prompt = rerank_prompt(question, original, [(a, it.text[:MAX_PASSAGE_CHARS]) for a, it in aliases.items()])
        data = await get_llm().complete_json(system=RERANK_SYSTEM, prompt=prompt, schema=RERANK_SCHEMA, max_tokens=8000)
        out: dict[str, float] = {}
        for row in data.get("scores", []):
            item = aliases.get(str(row.get("id", "")).strip())
            if item is None:
                continue
            try:
                out[item.key] = max(0.0, min(10.0, float(row.get("score", 0)))) / 10.0
            except (TypeError, ValueError):
                continue
        missing = [it.key for it in items if it.key not in out]
        if missing:
            log.warning("llm reranker omitted passages", extra={"fields": {"missing": len(missing)}})
        return out


class _HttpReranker:
    url = ""

    def __init__(self) -> None:
        if not settings.reranker_api_key:
            raise RuntimeError("RERANKER_API_KEY is not set")
        self._client = httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {settings.reranker_api_key}"})

    async def score(self, question, original, items):
        resp = await self._client.post(
            self.url,
            json={"model": self.model, "query": question, "documents": [it.text[:MAX_PASSAGE_CHARS] for it in items], "top_n": len(items)},
        )
        resp.raise_for_status()
        return {items[r["index"]].key: float(r["relevance_score"]) for r in resp.json()["results"]}


class CohereReranker(_HttpReranker):
    name = "cohere"
    default_min_score = 0.15
    url = "https://api.cohere.com/v2/rerank"

    @property
    def model(self) -> str:
        return settings.reranker_model or "rerank-v3.5"


class JinaReranker(_HttpReranker):
    name = "jina"
    default_min_score = 0.2
    url = "https://api.jina.ai/v1/rerank"

    @property
    def model(self) -> str:
        return settings.reranker_model or "jina-reranker-v2-base-multilingual"


@lru_cache
def get_reranker() -> Reranker:
    return {"llm": LLMReranker, "cohere": CohereReranker, "jina": JinaReranker, "none": NoReranker}[
        settings.reranker_provider
    ]()


def min_score(reranker: Reranker) -> float:
    return settings.rerank_min_score if settings.rerank_min_score is not None else reranker.default_min_score


async def rerank(question: str, original: str, items: list[RerankItem]) -> tuple[dict[str, float], str]:
    """Returns (scores, provider_used). Falls back to fusion order if the reranker fails."""
    reranker = get_reranker()
    try:
        return await asyncio.wait_for(reranker.score(question, original, items), timeout=60), reranker.name
    except (LLMError, httpx.HTTPError, asyncio.TimeoutError, KeyError) as exc:
        log.error("reranker failed; falling back to fusion order", extra={"fields": {"error": str(exc)[:200]}})
        return await NoReranker().score(question, original, items), "none(fallback)"
