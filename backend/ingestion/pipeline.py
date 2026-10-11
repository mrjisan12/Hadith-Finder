"""Ingestion pipeline stages. Each stage is idempotent and resumable (outputs are cached on disk).

  render     PDF page -> high-res grayscale PNG (for OCR) + compact 4-level PNG (viewer)
  ocr        PNG -> OcrPage JSON (engine-independent, with bounding boxes)
  layout     OcrPage -> PageLayout JSON (header, footer page number, paragraphs, headings)
  structure  all layouts -> printed-page mapping + section tree (+ CSV review report)
  load       write books/documents/sections/pages/paragraphs/chunks to PostgreSQL
  embed      embed chunks that have no vector for the current model (disk-cached)
  upload     push original PDF + page images to object storage
"""

from __future__ import annotations

import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select
from tqdm import tqdm

from app.core.config import settings
from app.core.logging import get_logger
from app.core.textnorm import search_key
from app.services.storage import get_storage, original_pdf_key, page_image_key
from ingestion.chunking import build_embed_text, split_paragraph, stable_id, text_hash
from ingestion.config import BookConfig
from ingestion.layout import RTL, PageLayout, analyse_page
from ingestion.ocr.base import OcrPage, get_ocr_provider
from ingestion.page_numbers import PageNumberResult, infer_page_numbers, load_overrides, summarise
from ingestion.sections import SectionPlan, build_sections

log = get_logger("ingestion")

LOW_CONFIDENCE = 0.80
CONTINUATION_CONTEXT_CHARS = 400


# =========================================================================== helpers
def pdf_page_count(cfg: BookConfig) -> int:
    import pymupdf

    with pymupdf.open(cfg.pdf) as doc:
        return doc.page_count


def parse_page_spec(spec: str | None, total: int) -> list[int]:
    """'1-20,25,30-' -> page list (1-based, inclusive)."""
    if not spec:
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else total
            pages.update(range(max(1, start), min(total, end) + 1))
        elif part:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= total)


def _png(cfg: BookConfig, p: int) -> Path:
    return cfg.ocr_image_dir / f"{p:04d}.png"


def _ocr_json(cfg: BookConfig, p: int) -> Path:
    return cfg.ocr_dir / f"{p:04d}.json"


def _layout_json(cfg: BookConfig, p: int) -> Path:
    return cfg.layout_dir / f"{p:04d}.json"


def _display_path(cfg: BookConfig, p: int) -> Path:
    storage = get_storage()
    key = page_image_key(cfg.slug, p)
    if storage.name == "local":
        return storage.local_path(key)
    return cfg.work_dir / "display" / f"{p:04d}.png"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# =========================================================================== split pages
def detect_split_pairs(doc) -> dict[int, int]:
    """Pairs of PDF pages that are two adjacent strips of ONE printed page.

    In this scan the operator sometimes split a page into two narrow PDF pages that both
    reference the same scanned image (e.g. PDF 189 + 190 = printed page ১৯৩). They are
    detected as: same image, both clearly narrower than normal, and the second strip starts
    exactly where the first ends. Returns {first_pdf_page: second_pdf_page} (1-based).
    """
    import statistics

    widths = [pg.rect.width for pg in doc]
    typical = statistics.median(widths)
    pairs: dict[int, int] = {}
    i = 0
    while i < doc.page_count - 1:
        a, b = doc[i], doc[i + 1]
        ia, ib = a.get_images(full=True), b.get_images(full=True)
        if (
            len(ia) == 1
            and len(ib) == 1
            and ia[0][0] == ib[0][0]
            and a.rect.width < 0.7 * typical
            and b.rect.width < 0.7 * typical
            and abs((a.get_image_bbox(ia[0]).x0 - b.get_image_bbox(ib[0]).x0) - a.rect.width) < 3
        ):
            pairs[i + 1] = i + 2
            i += 2
        else:
            i += 1
    return pairs


def split_pairs(cfg: BookConfig) -> dict[int, int]:
    """Cached detect_split_pairs for the book."""
    path = cfg.work_dir / "split_pages.json"
    if path.exists():
        return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    import pymupdf

    with pymupdf.open(cfg.pdf) as doc:
        pairs = detect_split_pairs(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pairs), encoding="utf-8")
    return pairs


def _merged_partner(pairs: dict[int, int]) -> dict[int, int]:
    """pdf_page -> partner pdf page, for both members of every split pair."""
    return {**pairs, **{b: a for a, b in pairs.items()}}


def _render_gray(pages, width_px: int):
    """Render one page, or several adjacent strips side by side, to a grayscale PIL image."""
    import pymupdf
    from PIL import Image

    zoom = width_px / sum(pg.rect.width for pg in pages)
    tiles = []
    for pg in pages:
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
        tiles.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    if len(tiles) == 1:
        return tiles[0]
    out = Image.new("L", (sum(t.width for t in tiles), max(t.height for t in tiles)), 255)
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width
    return out


# =========================================================================== render
def stage_render(cfg: BookConfig, pages: list[int], force: bool = False) -> None:
    import pymupdf

    cfg.ocr_image_dir.mkdir(parents=True, exist_ok=True)
    pairs = split_pairs(cfg)
    partner = _merged_partner(pairs)
    with pymupdf.open(cfg.pdf) as doc:
        for p in tqdm(pages, desc="render"):
            ocr_png, display_png = _png(cfg, p), _display_path(cfg, p)
            if not force and ocr_png.exists() and display_png.exists():
                continue
            if p in partner:  # one printed page split over two PDF pages: stitch the strips
                first = p if p in pairs else partner[p]
                source = [doc[first - 1], doc[first]]
            else:
                source = [doc[p - 1]]
            _render_gray(source, cfg.ocr_width_px).save(ocr_png)
            display_png.parent.mkdir(parents=True, exist_ok=True)
            # The scans are bitonal: 4 grey levels keep glyph edges smooth at ~1/3 of JPEG's size.
            _render_gray(source, cfg.display_width_px).quantize(colors=4).save(display_png, "PNG", optimize=True)


# =========================================================================== ocr
def stage_ocr(cfg: BookConfig, pages: list[int], force: bool = False, workers: int = 6) -> None:
    cfg.ocr_dir.mkdir(parents=True, exist_ok=True)
    seconds = set(split_pairs(cfg).values())  # OCR'd as part of the stitched first page
    todo = [p for p in pages if p not in seconds and (force or not _ocr_json(cfg, p).exists())]
    if not todo:
        log.info("ocr: nothing to do")
        return
    missing = [p for p in todo if not _png(cfg, p).exists()]
    if missing:
        raise RuntimeError(f"Render these pages first: {missing[:10]}{'...' if len(missing) > 10 else ''}")
    provider = get_ocr_provider(settings.ocr_provider)

    def run(p: int) -> int:
        result = provider.ocr(_png(cfg, p))
        _ocr_json(cfg, p).write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")
        return p

    failures: list[tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=workers if provider.name == "google_vision" else 1) as pool:
        futures = {pool.submit(run, p): p for p in todo}
        for fut in tqdm(as_completed(futures), total=len(futures), desc=f"ocr[{provider.name}]"):
            try:
                fut.result()
            except Exception as exc:  # keep going; failed pages are retried on the next run
                failures.append((futures[fut], str(exc)[:200]))
    if failures:
        log.error("ocr failures", extra={"fields": {"count": len(failures), "first": failures[:5]}})
        raise RuntimeError(f"OCR failed for {len(failures)} pages; re-run the ocr stage to retry them.")


# =========================================================================== layout
def stage_layout(cfg: BookConfig, pages: list[int], force: bool = False) -> None:
    cfg.layout_dir.mkdir(parents=True, exist_ok=True)
    pairs = split_pairs(cfg)
    firsts_by_second = {b: a for a, b in pairs.items()}
    for p in tqdm(pages, desc="layout"):
        src, dst = _ocr_json(cfg, p), _layout_json(cfg, p)
        if p in firsts_by_second:
            # Second strip of a split page: its text lives on the stitched first page.
            first_src = _ocr_json(cfg, firsts_by_second[p])
            if first_src.exists():
                d = json.loads(first_src.read_text(encoding="utf-8"))
                empty = PageLayout(pdf_page=p, width=d["width"], height=d["height"])
                dst.write_text(json.dumps(empty.to_dict(), ensure_ascii=False), encoding="utf-8")
            continue
        if not src.exists():
            continue
        if not force and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        ocr = OcrPage.from_dict(json.loads(src.read_text(encoding="utf-8")))
        layout = analyse_page(ocr, p)
        dst.write_text(json.dumps(layout.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def load_layouts(cfg: BookConfig) -> list[PageLayout]:
    out = []
    for f in sorted(cfg.layout_dir.glob("*.json")):
        out.append(PageLayout.from_dict(json.loads(f.read_text(encoding="utf-8"))))
    return out


# =========================================================================== structure
def infer_book_page_numbers(cfg: BookConfig, layouts: list[PageLayout]) -> list[PageNumberResult]:
    """Printed page numbers for every PDF page. A split pair counts as ONE printed page during
    inference (so gap arithmetic stays right) and both PDF pages then share its number."""
    pairs = split_pairs(cfg)
    seconds = {b: a for a, b in pairs.items()}
    overrides = load_overrides(cfg.page_mapping_path)
    detected = {lay.pdf_page: lay.footer_number for lay in layouts if lay.pdf_page not in seconds}
    results = {r.pdf_page: r for r in infer_page_numbers(detected, overrides)}
    for lay in layouts:
        second = lay.pdf_page
        if second in seconds and seconds[second] in results:
            first = results[seconds[second]]
            results[second] = PageNumberResult(second, None, first.printed, first.label, first.source, first.flag)
    for lay in layouts:  # an explicit override on a second page still wins
        if lay.pdf_page in seconds and lay.pdf_page in overrides:
            results[lay.pdf_page] = infer_page_numbers({lay.pdf_page: None}, {lay.pdf_page: overrides[lay.pdf_page]})[0]
    return [results[p] for p in sorted(results)]


def compute_structure(cfg: BookConfig, layouts: list[PageLayout]) -> tuple[list[PageNumberResult], SectionPlan]:
    numbers = infer_book_page_numbers(cfg, layouts)
    plan = build_sections(layouts, cfg.sections_path)
    return numbers, plan


def stage_structure(cfg: BookConfig) -> tuple[list[PageNumberResult], SectionPlan]:
    layouts = load_layouts(cfg)
    if not layouts:
        raise RuntimeError("No layout files found; run the render/ocr/layout stages first.")
    numbers, plan = compute_structure(cfg, layouts)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    by_page = {lay.pdf_page: lay for lay in layouts}

    with open(cfg.reports_dir / "page_numbers.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["pdf_page", "detected_footer", "printed_page", "source", "flag", "header", "ocr_conf", "paragraphs"])
        for r in numbers:
            lay = by_page[r.pdf_page]
            w.writerow([r.pdf_page, r.detected, r.label, r.source, r.flag or "", lay.header_text or "", lay.mean_conf, len(lay.paragraphs)])

    with open(cfg.reports_dir / "sections.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["level", "title", "start_pdf_page", "end_pdf_page", "source"])
        for s in plan.sections:
            w.writerow([s.level, s.title, s.start_pdf_page, s.end_pdf_page, s.source])

    summary = summarise(numbers)
    (cfg.reports_dir / "summary.json").write_text(
        json.dumps({"page_numbers": summary, "sections": len(plan.sections)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(
        "structure",
        extra={
            "fields": {
                "pages": summary["total"],
                "by_source": summary["by_source"],
                "needs_review": len(summary["needs_review"]),
                "level1_sections": sum(1 for s in plan.sections if s.level == 1),
                "chapters": sum(1 for s in plan.sections if s.level == 2),
                "report": str(cfg.reports_dir),
            }
        },
    )
    return numbers, plan


# =========================================================================== load
def _continuations(layouts: list[PageLayout], seconds: set[int]) -> set[int]:
    """PDF pages whose last paragraph continues on the next (text-bearing) page."""
    by_page = {lay.pdf_page: lay for lay in layouts}
    out = set()
    for lay in layouts:
        q = lay.pdf_page + 1
        nxt = by_page.get(q + 1 if q in seconds else q)
        if not (lay.ends_mid_paragraph and nxt and nxt.paragraphs):
            continue
        first = nxt.paragraphs[0]
        if first.kind == "text" and first.lang not in RTL and not first.starts_indented and not first.hadith_number:
            out.add(lay.pdf_page)
    return out


def stage_load(cfg: BookConfig) -> None:
    from app.core.database import session_scope
    from app.models import Book, Chunk, Document, Page, Paragraph, Section

    layouts = load_layouts(cfg)
    if not layouts:
        raise RuntimeError("No layout files found; run the earlier stages first.")
    numbers, plan = compute_structure(cfg, layouts)
    num_by_page = {r.pdf_page: r for r in numbers}
    pairs = split_pairs(cfg)
    partner = _merged_partner(pairs)
    continues = _continuations(layouts, set(pairs.values()))
    by_page = {lay.pdf_page: lay for lay in layouts}
    seconds = set(pairs.values())

    def neighbour(p: int, step: int) -> PageLayout | None:
        q = p + step
        if q in seconds:  # empty second strip of a split page; its text is on the first strip
            q += step
        return by_page.get(q)
    total_pages = pdf_page_count(cfg)
    pdf_sha = sha256_file(cfg.pdf)

    with session_scope() as db:
        book = db.scalar(select(Book).where(Book.slug == cfg.slug))
        if book is None:
            book = Book(slug=cfg.slug, title=cfg.title)
            db.add(book)
        book.title, book.title_native, book.author = cfg.title, cfg.title_native, cfg.author
        book.language, book.description, book.total_pages = cfg.language, cfg.description, total_pages
        db.flush()

        document = db.scalar(select(Document).where(Document.book_id == book.id, Document.sha256 == pdf_sha))
        if document is None:
            document = Document(book_id=book.id, filename=cfg.pdf.name, sha256=pdf_sha, page_count=total_pages)
            db.add(document)
        document.storage_path = original_pdf_key(cfg.slug)
        document.ocr_engine = settings.ocr_provider
        document.status = "loaded"
        db.flush()

        # Full, consistent rebuild of this book's structure (embeddings come back from the disk cache).
        db.execute(delete(Page).where(Page.book_id == book.id))
        db.execute(delete(Section).where(Section.book_id == book.id))
        db.flush()

        section_ids: dict[int, int] = {}
        for idx, spec in enumerate(plan.sections):
            if spec.level != 1:
                continue
            s = Section(book_id=book.id, level=1, ordinal=idx, title=spec.title,
                        start_pdf_page=spec.start_pdf_page, end_pdf_page=spec.end_pdf_page, source=spec.source)
            db.add(s)
            db.flush()
            section_ids[idx] = s.id
        for idx, spec in enumerate(plan.sections):
            if spec.level == 1:
                continue
            s = Section(book_id=book.id, level=spec.level, ordinal=idx, title=spec.title,
                        parent_id=section_ids.get(spec.parent) if spec.parent is not None else None,
                        start_pdf_page=spec.start_pdf_page, end_pdf_page=spec.end_pdf_page, source=spec.source)
            db.add(s)
            db.flush()
            section_ids[idx] = s.id
        section_titles = {idx: spec.title for idx, spec in enumerate(plan.sections)}

        n_paras = n_chunks = 0
        for lay in tqdm(layouts, desc="load"):
            p = lay.pdf_page
            num = num_by_page.get(p)
            sec_idx = plan.page_section.get(p)
            low_conf = lay.mean_conf is not None and lay.mean_conf < LOW_CONFIDENCE
            page = Page(
                book_id=book.id,
                document_id=document.id,
                pdf_page_number=p,
                merged_with_pdf_page=partner.get(p),
                printed_page_number=num.printed if num else None,
                printed_page_label=num.label if num else None,
                printed_page_source=num.source if num else "unknown",
                detected_printed_page=lay.footer_number,
                running_header=lay.header_text,
                section_id=section_ids.get(sec_idx) if sec_idx is not None else None,
                image_path=page_image_key(cfg.slug, p),
                width=lay.width,
                height=lay.height,
                ocr_engine=settings.ocr_provider,
                ocr_confidence=lay.mean_conf,
                ocr_text="\n\n".join(par.text for par in lay.paragraphs),
                needs_review=bool(low_conf or (num and (num.flag or num.source == "unknown"))),
            )
            db.add(page)
            db.flush()

            prev_lay, next_lay = neighbour(p, -1), neighbour(p, +1)
            last_text_idx = max((par.index for par in lay.paragraphs if par.kind == "text"), default=-1)
            for par in lay.paragraphs:
                chap_idx = plan.para_chapter.get((p, par.index))
                heading = plan.para_heading.get((p, par.index))
                cont_next = p in continues and par.index == last_text_idx
                cont_prev = prev_lay is not None and prev_lay.pdf_page in continues and par.index == 0
                paragraph = Paragraph(
                    source_id=stable_id("para", cfg.slug, p, par.index),
                    book_id=book.id,
                    page_id=page.id,
                    section_id=page.section_id,
                    chapter_id=section_ids.get(chap_idx) if chap_idx is not None else None,
                    paragraph_index=par.index,
                    kind=par.kind,
                    lang=par.lang,
                    heading=heading if heading != par.text else None,
                    text=par.text,
                    bbox=par.bbox,
                    line_boxes=par.line_boxes,
                    continues_on_next_page=cont_next,
                    continued_from_prev_page=cont_prev,
                    hadith_number=par.hadith_number,
                    ocr_confidence=par.conf,
                )
                db.add(paragraph)
                db.flush()
                n_paras += 1
                if par.kind != "text":
                    continue

                next_head = next_lay.paragraphs[0].text[:CONTINUATION_CONTEXT_CHARS] if cont_next and next_lay else None
                prev_tail = None
                if cont_prev and prev_lay:
                    prev_text = [x for x in prev_lay.paragraphs if x.kind == "text"]
                    prev_tail = prev_text[-1].text[-CONTINUATION_CONTEXT_CHARS:] if prev_text else None
                pieces = split_paragraph(par.text)
                for piece in pieces:
                    first, last = piece.chunk_index == 0, piece.chunk_index == len(pieces) - 1
                    embed_text = build_embed_text(
                        book_title=cfg.title_native or cfg.title,
                        section=section_titles.get(sec_idx) if sec_idx is not None else None,
                        chapter=section_titles.get(chap_idx) if chap_idx is not None else None,
                        heading=heading,
                        text=piece.text,
                        prev_tail=prev_tail if first else None,
                        next_head=next_head if last else None,
                    )
                    db.add(
                        Chunk(
                            source_id=stable_id("chunk", cfg.slug, p, par.index, piece.chunk_index),
                            book_id=book.id,
                            page_id=page.id,
                            paragraph_id=paragraph.id,
                            chunk_index=piece.chunk_index,
                            char_start=piece.char_start,
                            char_end=piece.char_end,
                            text=piece.text,
                            embed_text=embed_text,
                            search_text=search_key(f"{heading or ''} {piece.text}"),
                            text_hash=text_hash(piece.text),
                            lang=par.lang,
                        )
                    )
                    n_chunks += 1
        log.info("load complete", extra={"fields": {"book": cfg.slug, "pages": len(layouts), "paragraphs": n_paras, "chunks": n_chunks}})


# =========================================================================== embed
class _EmbeddingCache:
    """Append-only on-disk cache: sha256(model|embed_text) -> vector. Re-loads never re-pay the API."""

    def __init__(self, directory: Path, model_key: str) -> None:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in model_key)
        self.dir = directory / safe
        self.dir.mkdir(parents=True, exist_ok=True)
        self.model_key = model_key
        self.data: dict[str, np.ndarray] = {}
        for f in sorted(self.dir.glob("*.npz")):
            z = np.load(f)
            for h, v in zip(z["hashes"], z["vectors"]):
                self.data[str(h)] = v

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_key}|{text}".encode("utf-8")).hexdigest()

    def add(self, items: dict[str, list[float]]) -> None:
        if not items:
            return
        n = len(list(self.dir.glob("*.npz")))
        hashes = np.array(list(items.keys()))
        vectors = np.array(list(items.values()), dtype=np.float32)
        np.savez_compressed(self.dir / f"batch_{n:06d}.npz", hashes=hashes, vectors=vectors)
        self.data.update({h: v for h, v in zip(hashes, vectors)})


def stage_embed(cfg: BookConfig) -> None:
    from app.core.database import session_scope
    from app.embeddings.base import get_embedding_provider
    from app.models import Book, Chunk, Embedding

    provider = get_embedding_provider()
    model_key = f"{provider.model}@{provider.dim}"
    cache = _EmbeddingCache(cfg.embedding_cache_dir, model_key)

    with session_scope() as db:
        book = db.scalar(select(Book).where(Book.slug == cfg.slug))
        if book is None:
            raise RuntimeError("Book not loaded; run the load stage first.")
        done = select(Embedding.chunk_id).where(Embedding.model == model_key)
        rows = db.execute(
            select(Chunk.id, Chunk.embed_text).where(Chunk.book_id == book.id, Chunk.id.not_in(done)).order_by(Chunk.id)
        ).all()

    log.info("embed", extra={"fields": {"model": model_key, "to_embed": len(rows), "cached": len(cache.data)}})
    batch_size = settings.embedding_batch_size
    for i in tqdm(range(0, len(rows), batch_size), desc="embed"):
        batch = rows[i : i + batch_size]
        keys = [cache.key(text) for _, text in batch]
        missing = [(k, text) for k, (_, text) in zip(keys, batch) if k not in cache.data]
        if missing:
            vectors = provider.embed([t for _, t in missing], "document")
            cache.add({k: v for (k, _), v in zip(missing, vectors)})
        with session_scope() as db:
            db.add_all(
                Embedding(chunk_id=cid, model=model_key, embedding=cache.data[k].tolist(), text_hash=k)
                for (cid, _), k in zip(batch, keys)
            )


# =========================================================================== upload
def stage_upload(cfg: BookConfig, pages: list[int], force: bool = False) -> None:
    storage = get_storage()
    if storage.name == "supabase":
        storage.ensure_bucket()  # type: ignore[union-attr]
    pdf_key = original_pdf_key(cfg.slug)
    if force or not storage.exists(pdf_key):
        storage.put_file(pdf_key, cfg.pdf, "application/pdf")
    if storage.name == "local":
        return  # page images were rendered directly into local storage

    def up(p: int) -> None:
        key = page_image_key(cfg.slug, p)
        if force or not storage.exists(key):
            storage.put_file(key, _display_path(cfg, p), "image/png")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(tqdm(pool.map(up, pages), total=len(pages), desc="upload"))


# =========================================================================== mapping maintenance
def apply_mapping(cfg: BookConfig) -> dict:
    """Re-apply page_mapping.json (+ OCR inference) to the DB without re-ingesting anything."""
    from app.core.database import session_scope
    from app.models import Book, Page

    layouts = load_layouts(cfg)
    numbers = infer_book_page_numbers(cfg, layouts)
    changed = 0
    with session_scope() as db:
        book = db.scalar(select(Book).where(Book.slug == cfg.slug))
        if book is None:
            raise RuntimeError("Book not loaded.")
        pages = {pg.pdf_page_number: pg for pg in db.scalars(select(Page).where(Page.book_id == book.id))}
        for r in numbers:
            pg = pages.get(r.pdf_page)
            if pg is None:
                continue
            if (pg.printed_page_number, pg.printed_page_label, pg.printed_page_source) != (r.printed, r.label, r.source):
                changed += 1
            pg.printed_page_number, pg.printed_page_label, pg.printed_page_source = r.printed, r.label, r.source
            pg.needs_review = bool(r.flag or r.source == "unknown") and r.source != "manual"
    return {"changed": changed, **summarise(numbers)}


def set_page_override(cfg: BookConfig, pdf_page: int, printed: str | None) -> None:
    path = cfg.page_mapping_path
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pages": {}, "ranges": []}
    value: int | str | None
    if printed is None or printed.lower() in ("none", "null", ""):
        value = None
    else:
        value = int(printed) if printed.isdigit() else printed
    data.setdefault("pages", {})[str(pdf_page)] = value
    data["pages"] = dict(sorted(data["pages"].items(), key=lambda kv: int(kv[0])))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
