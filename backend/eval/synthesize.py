"""Build a large synthetic retrieval test set from the indexed book.

Samples random Bangla paragraphs and asks the LLM to write the kind of question a reader would
type (modern Bangla, NOT copying the passage's wording). Because each question is written from a
known paragraph, we know the correct page, so retrieval accuracy can be measured at scale:

  python -m eval.synthesize --n 150
  python -m eval.run_eval --dataset eval/datasets/synthetic.jsonl

Spot-check a sample of the generated questions before trusting the numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.logging import setup_logging
from app.generation.llm import LLMError, get_llm
from app.models import Chunk, Page, Paragraph

SYSTEM = """You write evaluation questions for a search engine over a Bangla Islamic book (Fazail-e-Amal).
Given ONE passage, write one question that a normal reader might type and that this passage answers
specifically. Rules: modern everyday Bangla (চলিত ভাষা) with modern spellings; do NOT copy distinctive
phrases from the passage; the question must be answerable from this passage alone; avoid yes/no.
Also return a short snippet (3-6 consecutive words copied exactly from the passage) that contains the answer.
If the passage is too fragmentary to ask anything meaningful, set usable=false."""
SCHEMA = {
    "type": "object",
    "properties": {"usable": {"type": "boolean"}, "question": {"type": "string"}, "snippet": {"type": "string"}},
    "required": ["usable", "question", "snippet"],
    "additionalProperties": False,
}


async def main_async(n: int, seed: int, out: Path) -> None:
    random.seed(seed)
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Chunk.text, Page.pdf_page_number, Page.printed_page_number)
            .join(Paragraph, Paragraph.id == Chunk.paragraph_id)
            .join(Page, Page.id == Chunk.page_id)
            .where(Chunk.lang == "bn", Paragraph.kind == "text", func.length(Chunk.text) > 250)
        ).all()
    finally:
        db.close()
    sample = random.sample(rows, min(n * 2, len(rows)))
    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for text, pdf_page, printed in sample:
            if written >= n:
                break
            try:
                data = await get_llm().complete_json(system=SYSTEM, prompt=f"<passage>\n{text}\n</passage>", schema=SCHEMA, max_tokens=2000)
            except LLMError as exc:
                print("skip:", exc)
                continue
            if not data.get("usable") or not data.get("question"):
                continue
            written += 1
            fh.write(
                json.dumps(
                    {
                        "id": f"s{written:03d}",
                        "question": data["question"],
                        "expected": [{"pdf_page": pdf_page, "printed_page": printed, "snippet": data.get("snippet", "")}],
                        "tags": ["synthetic"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            print(f"{written:>3}  PDF {pdf_page:<4} {data['question'][:70]}")
    print(f"\nWrote {written} questions to {out}")


def main() -> None:
    setup_logging("WARNING")
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "datasets" / "synthetic.jsonl"))
    a = p.parse_args()
    asyncio.run(main_async(a.n, a.seed, Path(a.out)))


if __name__ == "__main__":
    main()
