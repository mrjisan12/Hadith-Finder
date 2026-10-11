"""Evaluate Question -> correct source passage -> correct page reference.

  python -m eval.run_eval                               # retrieval only (cheap: no answer generation)
  python -m eval.run_eval --mode e2e                    # full chat pipeline (answers + citations)
  python -m eval.run_eval --mode e2e --judge            # + LLM groundedness judge
  python -m eval.run_eval --dataset eval/datasets/synthetic.jsonl

Metrics
  hit@1/3/5          an expected PDF page is among the top-k selected sources
  mrr                mean reciprocal rank of the first correct source
  paragraph@k        the expected snippet occurs in a top-k source's ORIGINAL paragraph
  printed_page_acc   for correct hits with a known printed page: printed page matches
  negatives          out-of-scope questions correctly answered "not enough evidence"
  citation_validity  (e2e) every cited id is a returned, database-backed source
  groundedness       (e2e --judge) every claim in the answer is supported by its cited passages
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from app.core.logging import setup_logging
from app.core.textnorm import fold_tokens
from app.schemas.source import SourceOut

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "datasets" / "fazail-e-amal.jsonl"

JUDGE_SYSTEM = """You check whether an answer is fully supported by the passages it cites.
The passages are OCR text from a Bangla Islamic book. For every factual claim in the answer, decide if
the cited passages support it. Ignore style. Return JSON."""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["supported", "unsupported_claims"],
    "additionalProperties": False,
}


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def snippet_in(snippet: str, text: str) -> bool:
    """OCR-tolerant containment test on folded text."""
    s, t = " ".join(fold_tokens(snippet, stem=False)), " ".join(fold_tokens(text, stem=False))
    return bool(s) and (s in t or fuzz.partial_ratio(s, t) >= 85)


def page_matches(src: SourceOut, pdf_page: int) -> bool:
    pages = {src.pdf_page}
    if src.pdf_page_end:
        pages.add(src.pdf_page_end)
    if src.continuation:
        pages.add(src.continuation.pdf_page)
    if src.previous_part:
        pages.add(src.previous_part.pdf_page)
    return pdf_page in pages


def score_item(item: dict, sources: list[SourceOut]) -> dict:
    expected = item.get("expected", [])
    first_rank = None
    para_rank = None
    printed_ok = None
    for rank, src in enumerate(sources, start=1):
        for exp in expected:
            if page_matches(src, exp["pdf_page"]):
                if first_rank is None:
                    first_rank = rank
                    if exp.get("printed_page") is not None and src.pdf_page == exp["pdf_page"]:
                        printed_ok = src.printed_page == exp["printed_page"]
                text = src.original_text
                if src.continuation:
                    text += " " + src.continuation.text
                if para_rank is None and exp.get("snippet") and snippet_in(exp["snippet"], text):
                    para_rank = rank
    return {"first_rank": first_rank, "paragraph_rank": para_rank, "printed_ok": printed_ok}


async def run_retrieval(item: dict) -> tuple[list[SourceOut], dict]:
    from app.retrieval.hybrid import retrieve
    from app.retrieval.query_understanding import understand_query

    plan = await understand_query(item["question"], [])
    if not plan.in_scope:
        return [], {"insufficient": True, "in_scope": False}
    result = await retrieve(plan)
    return [s.source for s in result.selected], {"insufficient": not result.selected, "in_scope": True}


async def run_e2e(item: dict, judge: bool) -> tuple[list[SourceOut], dict]:
    from app.schemas.chat import ChatRequest
    from app.services.chat_service import chat_once

    resp = await chat_once(ChatRequest(query=item["question"]))
    returned = {s.source_id for s in resp.sources}
    cited = [s for s in resp.sources if s.cited]
    from app.citation.verify import extract_citations

    in_answer = extract_citations(resp.answer)
    extra = {
        "insufficient": resp.insufficient_evidence,
        "answer": resp.answer,
        "citations_valid": all(c in returned for c in in_answer),
        "n_cited": len(cited),
    }
    if judge and cited and not resp.insufficient_evidence:
        from app.generation.llm import get_llm

        passages = "\n\n".join(f"[{s.source_id}]\n{s.original_text}" for s in cited)
        verdict = await get_llm().complete_json(
            system=JUDGE_SYSTEM,
            prompt=f"<passages>\n{passages}\n</passages>\n\n<answer>\n{resp.answer}\n</answer>",
            schema=JUDGE_SCHEMA,
        )
        extra["grounded"] = bool(verdict.get("supported"))
        extra["unsupported_claims"] = verdict.get("unsupported_claims", [])
    # Rank by what the user sees: cited sources first, then the rest.
    return [*cited, *[s for s in resp.sources if not s.cited]], extra


def pct(xs: list[bool]) -> str:
    return f"{100 * sum(xs) / len(xs):.1f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"


async def main_async(args) -> None:
    items = load_dataset(Path(args.dataset))
    if args.limit:
        items = items[: args.limit]
    rows = []
    for item in items:
        t0 = time.perf_counter()
        try:
            if args.mode == "e2e":
                sources, extra = await run_e2e(item, args.judge)
            else:
                sources, extra = await run_retrieval(item)
            error = None
        except Exception as exc:  # keep evaluating the rest
            sources, extra, error = [], {}, f"{type(exc).__name__}: {exc}"
        row = {
            "id": item["id"],
            "question": item["question"],
            "expect_insufficient": bool(item.get("expect_insufficient")),
            **score_item(item, sources),
            **extra,
            "top_sources": [
                {"source_id": s.source_id, "pdf_page": s.pdf_page, "printed_page": s.printed_page_label, "score": s.relevance_score}
                for s in sources[:5]
            ],
            "seconds": round(time.perf_counter() - t0, 2),
            "error": error,
        }
        rows.append(row)
        mark = "NEG" if row["expect_insufficient"] else (f"rank {row['first_rank']}" if row["first_rank"] else "MISS")
        print(f"{row['id']:<6} {mark:<8} {row['seconds']:>5}s  {item['question'][:60]}")

    pos = [r for r in rows if not r["expect_insufficient"]]
    neg = [r for r in rows if r["expect_insufficient"]]
    summary = {
        "dataset": str(args.dataset),
        "mode": args.mode,
        "n_positive": len(pos),
        "n_negative": len(neg),
        "hit@1": pct([r["first_rank"] == 1 for r in pos]),
        "hit@3": pct([bool(r["first_rank"]) and r["first_rank"] <= 3 for r in pos]),
        "hit@5": pct([bool(r["first_rank"]) and r["first_rank"] <= 5 for r in pos]),
        "mrr": round(statistics.mean([1 / r["first_rank"] if r["first_rank"] else 0 for r in pos]), 4) if pos else None,
        "paragraph@5": pct([bool(r["paragraph_rank"]) for r in pos]),
        "printed_page_acc": pct([r["printed_ok"] for r in pos if r["printed_ok"] is not None]),
        "wrongly_insufficient": pct([bool(r.get("insufficient")) for r in pos]),
        "negatives_correct": pct([bool(r.get("insufficient")) for r in neg]),
        "errors": sum(1 for r in rows if r["error"]),
        "median_seconds": statistics.median([r["seconds"] for r in rows]) if rows else None,
    }
    if args.mode == "e2e":
        summary["citation_validity"] = pct([r.get("citations_valid", False) for r in rows if "citations_valid" in r])
        if args.judge:
            summary["groundedness"] = pct([r["grounded"] for r in rows if "grounded" in r])

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"{Path(args.dataset).stem}-{args.mode}-{stamp}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nDetailed results: {out}")


def main() -> None:
    setup_logging("WARNING")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--mode", choices=["retrieval", "e2e"], default="retrieval")
    p.add_argument("--judge", action="store_true", help="LLM groundedness judge (e2e only)")
    p.add_argument("--limit", type=int, default=0)
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
