"""Reciprocal Rank Fusion of several ranked lists."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval.search import Hit

RRF_K = 60


@dataclass
class Candidate:
    chunk_id: int
    fused_score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)  # list name -> 1-based rank
    raw_scores: dict[str, float] = field(default_factory=dict)
    rerank_score: float | None = None
    source_id: str | None = None  # filled once the chunk row is loaded


def rrf_fuse(lists: dict[str, list[Hit]], weights: dict[str, float] | None = None, k: int = RRF_K) -> list[Candidate]:
    weights = weights or {}
    cands: dict[int, Candidate] = {}
    for name, hits in lists.items():
        w = weights.get(name, 1.0)
        for rank, hit in enumerate(hits, start=1):
            c = cands.setdefault(hit.chunk_id, Candidate(chunk_id=hit.chunk_id))
            c.fused_score += w / (k + rank)
            c.ranks[name] = rank
            c.raw_scores[name] = round(hit.score, 5)
    return sorted(cands.values(), key=lambda c: (-c.fused_score, c.chunk_id))
