"""Engine-independent OCR result model.

Every OCR provider converts its output into `OcrPage` -> blocks -> lines -> words, with pixel
bounding boxes. The layout stage only depends on this model, so OCR engines are swappable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels


def union_bbox(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


@dataclass
class OcrWord:
    text: str
    bbox: BBox
    conf: float | None = None


@dataclass
class OcrLine:
    words: list[OcrWord]
    text: str
    bbox: BBox
    conf: float | None = None
    block_index: int = 0

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class OcrBlock:
    lines: list[OcrLine]
    bbox: BBox


@dataclass
class OcrPage:
    width: int
    height: int
    engine: str
    blocks: list[OcrBlock] = field(default_factory=list)

    @property
    def lines(self) -> list[OcrLine]:
        return [ln for b in self.blocks for ln in b.lines]

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    @property
    def mean_conf(self) -> float | None:
        confs = [w.conf for ln in self.lines for w in ln.words if w.conf is not None]
        return round(sum(confs) / len(confs), 4) if confs else None

    # ------------------------------------------------------------ (de)serialisation
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> OcrPage:
        blocks = []
        for b in d.get("blocks", []):
            lines = [
                OcrLine(
                    words=[OcrWord(text=w["text"], bbox=tuple(w["bbox"]), conf=w.get("conf")) for w in ln["words"]],
                    text=ln["text"],
                    bbox=tuple(ln["bbox"]),
                    conf=ln.get("conf"),
                    block_index=ln.get("block_index", 0),
                )
                for ln in b["lines"]
            ]
            blocks.append(OcrBlock(lines=lines, bbox=tuple(b["bbox"])))
        return cls(width=d["width"], height=d["height"], engine=d["engine"], blocks=blocks)


class OcrProvider(Protocol):
    name: str

    def ocr(self, image_path: Path) -> OcrPage: ...


def get_ocr_provider(name: str) -> OcrProvider:
    if name == "google_vision":
        from ingestion.ocr.google_vision import GoogleVisionOcr

        return GoogleVisionOcr()
    if name == "tesseract":
        from ingestion.ocr.tesseract import TesseractOcr

        return TesseractOcr()
    raise ValueError(f"Unknown OCR provider: {name}")
