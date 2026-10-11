from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import BACKEND_DIR, PROJECT_ROOT, settings

BOOKS_DIR = BACKEND_DIR / "ingestion" / "books"


@dataclass
class BookConfig:
    slug: str
    title: str
    title_native: str | None
    author: str | None
    language: str
    description: str | None
    pdf: Path
    config_dir: Path
    ocr_width_px: int = 2400  # OCR render width (the scans are ~2544 px wide natively)
    display_width_px: int = 1600  # page image shown in the viewer

    # ------------------------------------------------------------------ paths
    @property
    def work_dir(self) -> Path:
        return Path(settings.data_dir) / "work" / self.slug

    @property
    def ocr_image_dir(self) -> Path:
        return self.work_dir / "ocr_images"

    @property
    def ocr_dir(self) -> Path:
        return self.work_dir / "ocr"

    @property
    def layout_dir(self) -> Path:
        return self.work_dir / "layout"

    @property
    def reports_dir(self) -> Path:
        return self.work_dir / "reports"

    @property
    def embedding_cache_dir(self) -> Path:
        return self.work_dir / "embedding_cache"

    @property
    def page_mapping_path(self) -> Path:
        return self.config_dir / "page_mapping.json"

    @property
    def sections_path(self) -> Path:
        return self.config_dir / "sections.json"


def load_book_config(slug_or_path: str) -> BookConfig:
    p = Path(slug_or_path)
    cfg_path = p if p.suffix in (".yaml", ".yml") else BOOKS_DIR / slug_or_path / "book.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    pdf = Path(data["pdf"])
    if not pdf.is_absolute():
        pdf = (PROJECT_ROOT / pdf).resolve()
    return BookConfig(
        slug=data["slug"],
        title=data["title"],
        title_native=data.get("title_native"),
        author=data.get("author"),
        language=data.get("language", "bn"),
        description=data.get("description"),
        pdf=pdf,
        config_dir=cfg_path.parent,
        ocr_width_px=int(data.get("ocr_width_px", 2400)),
        display_width_px=int(data.get("display_width_px", 1600)),    )
