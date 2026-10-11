"""Tesseract fallback (free, offline).

Requires the Tesseract binary plus `ben`, `ara` and `urd` traineddata
(Windows: https://github.com/UB-Mannheim/tesseract/wiki). Bangla accuracy is noticeably
lower than Google Vision on this book, so use it for development/offline work only.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from app.core.config import settings
from ingestion.ocr.base import OcrBlock, OcrLine, OcrPage, OcrWord, union_bbox


class TesseractOcr:
    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract

        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        self._tess = pytesseract

    def ocr(self, image_path: Path) -> OcrPage:
        from PIL import Image

        with Image.open(image_path) as img:
            width, height = img.size
            data = self._tess.image_to_data(
                img, lang=settings.tesseract_langs, config="--psm 3", output_type=self._tess.Output.DICT
            )

        grouped: OrderedDict[tuple[int, int, int], list[OcrWord]] = OrderedDict()
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            conf = float(data["conf"][i])
            grouped.setdefault(key, []).append(
                OcrWord(text=text, bbox=(x, y, x + w, y + h), conf=conf / 100 if conf >= 0 else None)
            )

        page = OcrPage(width=width, height=height, engine="tesseract")
        blocks: OrderedDict[int, list[OcrLine]] = OrderedDict()
        for (block_num, _par, _line), words in grouped.items():
            confs = [w.conf for w in words if w.conf is not None]
            blocks.setdefault(block_num, []).append(
                OcrLine(
                    words=words,
                    text=" ".join(w.text for w in words),
                    bbox=union_bbox([w.bbox for w in words]),
                    conf=sum(confs) / len(confs) if confs else None,
                    block_index=block_num,
                )
            )
        for lines in blocks.values():
            page.blocks.append(OcrBlock(lines=lines, bbox=union_bbox([ln.bbox for ln in lines])))
        return page
