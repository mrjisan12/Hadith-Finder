"""Split-page detection against the real scanned PDF (skipped if the PDF is not present)."""

import pytest

from app.core.config import PROJECT_ROOT
from ingestion.layout import PageLayout
from ingestion.pipeline import detect_split_pairs, infer_book_page_numbers

PDF = PROJECT_ROOT / "sources" / "fazail-e-amal.pdf"


@pytest.mark.skipif(not PDF.exists(), reason="source PDF not present")
def test_detects_every_split_printed_page_in_the_book():
    import pymupdf

    with pymupdf.open(PDF) as doc:
        pairs = detect_split_pairs(doc)
    assert pairs == {189: 190, 199: 200, 603: 604, 869: 870, 875: 876, 971: 972}


def test_split_pair_counts_as_one_printed_page(tmp_path, monkeypatch):
    import ingestion.pipeline as pl
    from ingestion.config import BookConfig

    cfg = BookConfig(slug="t", title="t", title_native=None, author=None, language="bn", description=None,
                     pdf=tmp_path / "x.pdf", config_dir=tmp_path)
    monkeypatch.setattr(pl, "split_pairs", lambda _cfg: {189: 190})
    # printed 192 at pdf 188, 193 spans pdf 189+190, 194 at pdf 191
    footers = {186: 190, 187: 191, 188: 192, 189: 193, 190: None, 191: 194, 192: 195}
    layouts = [PageLayout(pdf_page=p, width=1, height=1, footer_number=f) for p, f in footers.items()]
    r = {x.pdf_page: x for x in infer_book_page_numbers(cfg, layouts)}
    assert r[189].printed == 193 and r[190].printed == 193
    assert r[191].printed == 194 and r[191].source == "ocr"
