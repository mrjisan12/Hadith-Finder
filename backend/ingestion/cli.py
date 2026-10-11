"""Ingestion CLI.

  python -m ingestion run fazail-e-amal                      # full pipeline
  python -m ingestion run fazail-e-amal --pages 1-20         # try a few pages first
  python -m ingestion run fazail-e-amal --stages layout,structure,load,embed
  python -m ingestion report fazail-e-amal                   # printed-page review report
  python -m ingestion set-page fazail-e-amal 263 266         # manual correction (+ applies it)
  python -m ingestion apply-mapping fazail-e-amal
  python -m ingestion inspect fazail-e-amal 263              # show what was extracted from a page
"""

from __future__ import annotations

import json

import typer

from app.core.config import settings
from app.core.logging import setup_logging
from ingestion import pipeline
from ingestion.config import load_book_config

app = typer.Typer(add_completion=False, help="Hadith Finder ingestion pipeline")

ALL_STAGES = ["render", "ocr", "layout", "structure", "load", "embed", "upload"]


@app.callback()
def _setup() -> None:
    setup_logging(settings.log_level)


@app.command()
def run(
    book: str = typer.Argument(..., help="Book slug (folder under ingestion/books) or path to book.yaml"),
    pages: str = typer.Option(None, help="Page selection for render/ocr/layout/upload, e.g. '1-20,263'"),
    stages: str = typer.Option(",".join(ALL_STAGES), help="Comma-separated stages to run"),
    force: bool = typer.Option(False, help="Redo cached work for the selected stages"),
    workers: int = typer.Option(6, help="Parallel OCR requests"),
) -> None:
    cfg = load_book_config(book)
    selected = [s.strip() for s in stages.split(",") if s.strip()]
    unknown = set(selected) - set(ALL_STAGES)
    if unknown:
        raise typer.BadParameter(f"Unknown stages: {unknown}")
    page_list = pipeline.parse_page_spec(pages, pipeline.pdf_page_count(cfg))
    typer.echo(f"Book: {cfg.title} | pages selected: {len(page_list)} | stages: {selected}")

    if "render" in selected:
        pipeline.stage_render(cfg, page_list, force)
    if "ocr" in selected:
        pipeline.stage_ocr(cfg, page_list, force, workers)
    if "layout" in selected:
        pipeline.stage_layout(cfg, page_list, force)
    if "structure" in selected:
        pipeline.stage_structure(cfg)
    if "load" in selected:
        pipeline.stage_load(cfg)
    if "embed" in selected:
        pipeline.stage_embed(cfg)
    if "upload" in selected:
        pipeline.stage_upload(cfg, page_list, force)
    typer.echo("Done.")


@app.command()
def report(book: str) -> None:
    """Regenerate the page-number / section review reports (data/work/<book>/reports)."""
    cfg = load_book_config(book)
    numbers, _ = pipeline.stage_structure(cfg)
    review = [r for r in numbers if r.flag or r.source == "unknown"]
    typer.echo(f"{len(review)} pages need review. See {cfg.reports_dir / 'page_numbers.csv'}")
    for r in review[:40]:
        typer.echo(f"  PDF {r.pdf_page:>4}: detected={r.detected} -> printed={r.label} [{r.source}/{r.flag}]")


@app.command("set-page")
def set_page(book: str, pdf_page: int, printed: str = typer.Argument(..., help="Printed number, a label like 'iv', or 'none'")) -> None:
    """Record a manual PDF->printed page correction in page_mapping.json and apply it to the DB."""
    cfg = load_book_config(book)
    pipeline.set_page_override(cfg, pdf_page, printed)
    typer.echo(json.dumps(pipeline.apply_mapping(cfg)["by_source"], ensure_ascii=False))


@app.command("apply-mapping")
def apply_mapping(book: str) -> None:
    """Re-apply page_mapping.json to the database (no re-OCR needed)."""
    cfg = load_book_config(book)
    result = pipeline.apply_mapping(cfg)
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "needs_review"}, ensure_ascii=False))


@app.command()
def inspect(book: str, pdf_page: int) -> None:
    """Print the layout analysis of one page (header, footer number, paragraphs)."""
    cfg = load_book_config(book)
    path = cfg.layout_dir / f"{pdf_page:04d}.json"
    if not path.exists():
        raise typer.BadParameter(f"No layout for page {pdf_page}; run render/ocr/layout for it.")
    lay = json.loads(path.read_text(encoding="utf-8"))
    typer.echo(f"PDF page {pdf_page} | header: {lay['header_text']!r} | footer number: {lay['footer_number']} | conf: {lay['mean_conf']}")
    for p in lay["paragraphs"]:
        flag = f" [{p['kind']}]" if p["kind"] != "text" else ""
        hn = f" #{p['hadith_number']}" if p["hadith_number"] else ""
        typer.echo(f"\n--- ¶{p['index']} ({p['lang']}){flag}{hn}\n{p['text']}")


if __name__ == "__main__":
    app()
