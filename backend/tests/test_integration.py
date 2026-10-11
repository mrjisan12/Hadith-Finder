"""End-to-end test against a real PostgreSQL + pgvector database, with stub OCR/LLM/embeddings.

Runs only when TEST_DATABASE_URL is set, e.g.
    docker compose up -d db
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/hadith pytest tests/test_integration.py

It uses its own book slug ("itest-book") and removes it afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

SLUG = "itest-book"
HADITH = (
    "(৩৬) হযরত ইবনে ওমর (রাযিঃ) হইতে বর্ণিত, হুযূর সাল্লাল্লাহু আলাইহি ওয়াসাল্লাম এরশাদ করিয়াছেন, "
    "তিন ব্যক্তি এমন হইবে যাহারা কিয়ামতের ভয়ংকর বিপদেও ভীত হইবে না।"
)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    os.environ["DATABASE_URL"] = TEST_DB
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    os.environ["STORAGE_BACKEND"] = "local"
    os.environ["ENABLE_DEBUG"] = "true"
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    from sqlalchemy import delete

    from app.core.database import session_scope
    from app.models import Book

    with session_scope() as db:
        db.execute(delete(Book).where(Book.slug == SLUG))


# ----------------------------------------------------------------------------- stubs
class HashEmbeddings:
    """Bag of folded tokens -> hashed 1024-d vector. Deterministic, no network."""

    model = "stub-hash"
    dim = 1024

    def embed(self, texts, input_type):
        from app.core.textnorm import fold_tokens

        out = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            for tok in fold_tokens(t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1
            n = np.linalg.norm(v) or 1.0
            out.append((v / n).tolist())
        return out


class StubLLM:
    def __init__(self):
        self.answer_prompt = None

    async def complete_json(self, *, system, prompt, schema, max_tokens=8000):
        if "standalone_question" in schema["properties"]:
            return {
                "standalone_question": "কিয়ামতের দিন কোন তিন ব্যক্তি ভীত হইবে না?",
                "language": "bn",
                "in_scope": True,
                "search_queries": ["কিয়ামতের দিন তিন ব্যক্তি ভীত হইবে না", "ইবনে ওমর তিন ব্যক্তি"],
                "keywords": ["কিয়ামত", "তিন ব্যক্তি", "ইবনে উমর"],
                "hypothetical_passage": "তিন ব্যক্তি কিয়ামতের দিন ভীত হইবে না।",
            }
        # rerank: passage mentioning তিন ব্যক্তি gets 9, others 1
        import re

        scores = []
        for pid, body in re.findall(r'<passage id="(p\d+)">\n(.*?)\n</passage>', prompt, re.S):
            scores.append({"id": pid, "score": 9 if "তিন ব্যক্তি" in body else 1})
        return {"scores": scores}

    async def stream_answer(self, *, system, messages, max_tokens):
        import re

        self.answer_prompt = messages[0]["content"]
        ids = re.findall(r'id="(chunk_[0-9a-f]{10})"', self.answer_prompt)
        for piece in ["কিয়ামতের দিন তিন ব্যক্তি ভীত হইবে না ", f"[{ids[0]}]", "। ভুল উৎস ", "[chunk_0000000000]", "।"]:
            yield piece


@pytest.fixture(scope="module")
def loaded(env):
    from ingestion import pipeline
    from ingestion.config import BookConfig
    from ingestion.layout import analyse_page
    from tests.test_layout import L, R, block, build_page, line

    from app.core.config import PROJECT_ROOT, settings
    from pathlib import Path

    cfg = BookConfig(
        slug=SLUG, title="Integration Test Book", title_native="পরীক্ষা", author=None, language="bn",
        description=None, pdf=PROJECT_ROOT / "sources" / "fazail-e-amal.pdf",
        config_dir=Path(settings.data_dir) / "cfg",
    )
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    cfg.layout_dir.mkdir(parents=True, exist_ok=True)

    from ingestion.ocr.base import OcrPage

    def simple_page(footer: str, first_line: str, indented: bool) -> OcrPage:
        header = block(line("ফাযায়েলে কুরআন-৭৫", 850, 50, 1550, block=0))
        body = block(
            line(first_line, L + (90 if indented else 0), 300, R, block=1),
            line("এই অংশ অন্য বিষয়ে আলোচনা করে এবং শেষ হয়।", L, 390, 1200, block=1),
        )
        foot = block(line(footer, 1120, 3560, 1280, block=2))
        return OcrPage(width=2400, height=3700, engine="test", blocks=[header, body, foot])

    page263 = build_page()
    page263.blocks[3].lines[0].text = HADITH[:70]
    page263.blocks[3].lines[1].text = HADITH[70:]
    pages = {
        262: simple_page("২৬৫", "নামাযের ফযীলত সম্পর্কে একটি দীর্ঘ আলোচনা এখানে রহিয়াছে যাহা", True),
        263: page263,
        264: simple_page("২৬৭", "নিশ্চিন্ত থাকিতে পারে না এবং এই বর্ণনা এখানে শেষ হইয়াছে বলিয়া ধরা হইবে", False),
    }
    for p, ocr in pages.items():
        (cfg.layout_dir / f"{p:04d}.json").write_text(json.dumps(analyse_page(ocr, p).to_dict(), ensure_ascii=False), encoding="utf-8")

    import app.embeddings.base as emb

    stub = HashEmbeddings()
    emb.get_embedding_provider.cache_clear()
    orig = emb.get_embedding_provider
    emb.get_embedding_provider = lambda: stub
    pipeline.stage_load(cfg)
    pipeline.stage_embed(cfg)
    yield cfg, stub
    emb.get_embedding_provider = orig


@pytest.fixture()
def stubs(loaded, monkeypatch):
    _, embedder = loaded
    llm = StubLLM()
    import app.embeddings.base as emb
    import app.generation.answer as answer
    import app.reranking.base as rr
    import app.retrieval.hybrid as hybrid
    import app.retrieval.query_understanding as qu

    monkeypatch.setattr(emb, "get_embedding_provider", lambda: embedder)
    monkeypatch.setattr(hybrid, "get_embedding_provider", lambda: embedder)
    monkeypatch.setattr(qu, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_llm", lambda: llm)
    monkeypatch.setattr(answer, "get_llm", lambda: llm)
    monkeypatch.setattr(rr, "get_reranker", lambda: rr.LLMReranker())
    monkeypatch.setattr(hybrid, "get_reranker", lambda: rr.LLMReranker())
    qu._cache.clear()
    return llm


def test_pages_have_printed_numbers(loaded):
    from sqlalchemy import select

    from app.core.database import session_scope
    from app.models import Book, Page

    with session_scope() as db:
        book = db.scalar(select(Book).where(Book.slug == SLUG))
        pages = {p.pdf_page_number: p for p in db.scalars(select(Page).where(Page.book_id == book.id))}
    assert pages[263].printed_page_number == 266
    assert pages[263].printed_page_source == "ocr"
    assert pages[262].printed_page_number == 265


def test_chat_returns_verified_database_text(stubs):
    import asyncio

    from sqlalchemy import select

    from app.core.database import session_scope
    from app.models import Paragraph
    from app.schemas.chat import ChatRequest
    from app.services.chat_service import chat_once

    resp = asyncio.run(chat_once(ChatRequest(query="কিয়ামতের দিন কোন তিন ব্যক্তি ভয় পাবে না?", debug=True)))
    assert not resp.insufficient_evidence
    assert resp.sources, resp.debug
    sizes = resp.debug["list_sizes"]
    assert sizes["vec_question"] > 0 and sizes["vec_hyde"] > 0, sizes
    assert sizes["fts"] > 0, sizes  # folded full-text search on Bangla
    assert sizes["trigram"] > 0, sizes  # fuzzy trigram search
    top_debug = next(c for c in resp.debug["candidates"] if c["selected"])
    assert "fts" in top_debug["ranks"] and top_debug["rerank_score"] == 0.9
    top = resp.sources[0]
    assert top.cited and top.pdf_page == 263 and top.printed_page == 266
    assert "তিন ব্যক্তি" in top.original_text
    with session_scope() as db:
        para = db.scalar(select(Paragraph).where(Paragraph.source_id == top.paragraph_id))
        assert top.original_text == para.text  # exact DB text, not LLM text
    assert "chunk_0000000000" not in resp.answer  # fabricated citation removed
    assert f"[{top.source_id}]" in resp.answer
    assert all(s.source_id in {c["source_id"] for c in resp.debug["candidates"]} for s in resp.sources)


def test_continuation_across_page_break(stubs):
    from sqlalchemy import select

    from app.citation.verify import load_sources
    from app.core.database import session_scope
    from app.models import Chunk, Page, Paragraph

    with session_scope() as db:
        last = db.execute(
            select(Chunk.source_id)
            .join(Paragraph, Paragraph.id == Chunk.paragraph_id)
            .join(Page, Page.id == Chunk.page_id)
            .where(Page.pdf_page_number == 263, Paragraph.continues_on_next_page.is_(True))
        ).scalar()
        assert last is not None
        src = load_sources(db, [last])[last]
    assert src.continuation is not None and src.continuation.pdf_page == 264
    assert src.continuation.printed_page == 267


def test_http_api(stubs):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/health").json()["database"] == "ok"
    books = client.get("/api/v1/books").json()
    book = next(b for b in books if b["slug"] == SLUG)
    assert book["indexed_pages"] == 3

    with client.stream("POST", "/api/v1/chat/stream", json={"query": "তিন ব্যক্তি কিয়ামতে ভীত হইবে না কেন?"}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "status" and types[-1] == "final" and "sources" in types and "delta" in types
    final = events[-1]
    src = final["sources"][0]
    assert client.get(f"/api/v1/sources/{src['source_id']}").json()["original_text"] == src["original_text"]
    page = client.get(f"/api/v1/pages/{src['page_id']}").json()
    assert page["printed_page"] == 266 and page["next_page_id"] is not None
    assert client.get("/api/v1/sources/chunk_zzzz").status_code == 422
    assert client.get("/api/v1/sources/chunk_0000000000").status_code == 404
