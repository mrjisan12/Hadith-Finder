"""Google Cloud Vision DOCUMENT_TEXT_DETECTION (REST, API-key auth).

Chosen as the primary engine because it is strong on Bangla, handles mixed Bangla/Arabic/Urdu
pages, is deterministic (it cannot "invent" text the way an LLM-based OCR can) and returns
symbol-level bounding boxes and confidences.

Pricing: first 1000 pages/month free, then ~US$1.50 per 1000 pages.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from ingestion.ocr.base import OcrBlock, OcrLine, OcrPage, OcrWord, union_bbox

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
LANGUAGE_HINTS = ["bn", "ar", "ur"]

_LINE_END_BREAKS = {"EOL_SURE_SPACE", "LINE_BREAK", "HYPHEN"}
_SPACE_BREAKS = {"SPACE", "SURE_SPACE"}


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


def _box(poly: dict) -> tuple[float, float, float, float]:
    vs = poly.get("vertices", [])
    xs = [v.get("x", 0) for v in vs] or [0]
    ys = [v.get("y", 0) for v in vs] or [0]
    return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))


class GoogleVisionOcr:
    name = "google_vision"

    def __init__(self) -> None:
        if not settings.google_vision_api_key:
            raise RuntimeError("GOOGLE_VISION_API_KEY is not set (or set OCR_PROVIDER=tesseract).")
        self._client = httpx.Client(timeout=120)

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, max=60),
        reraise=True,
    )
    def _annotate(self, content_b64: str) -> dict:
        body = {
            "requests": [
                {
                    "image": {"content": content_b64},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "imageContext": {"languageHints": LANGUAGE_HINTS},
                }
            ]
        }
        # The key goes in a header, not the URL, so it can never end up in an access log.
        resp = self._client.post(ENDPOINT, json=body, headers={"X-Goog-Api-Key": settings.google_vision_api_key})
        if resp.status_code in (400, 401, 403):  # configuration problems: surface Google's own explanation
            try:
                reason = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                reason = resp.text[:300]
            raise RuntimeError(f"Google Vision {resp.status_code}: {reason}")
        resp.raise_for_status()
        result = resp.json()["responses"][0]
        if "error" in result:
            raise RuntimeError(f"Vision API error: {result['error'].get('message')}")
        return result

    def ocr(self, image_path: Path) -> OcrPage:
        content = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        result = self._annotate(content)
        return self.parse(result)

    @staticmethod
    def parse(result: dict) -> OcrPage:
        annotation = result.get("fullTextAnnotation") or {}
        pages = annotation.get("pages") or [{}]
        vpage = pages[0]
        page = OcrPage(width=int(vpage.get("width", 0)), height=int(vpage.get("height", 0)), engine="google_vision")

        for b_index, vblock in enumerate(vpage.get("blocks", [])):
            lines: list[OcrLine] = []
            cur_words: list[OcrWord] = []
            cur_text: list[str] = []

            def flush() -> None:
                if cur_words:
                    text = "".join(cur_text).strip()
                    if text:
                        confs = [w.conf for w in cur_words if w.conf is not None]
                        lines.append(
                            OcrLine(
                                words=list(cur_words),
                                text=text,
                                bbox=union_bbox([w.bbox for w in cur_words]),
                                conf=sum(confs) / len(confs) if confs else None,
                                block_index=b_index,
                            )
                        )
                cur_words.clear()
                cur_text.clear()

            for vpara in vblock.get("paragraphs", []):
                for vword in vpara.get("words", []):
                    symbols = vword.get("symbols", [])
                    word_text = "".join(s.get("text", "") for s in symbols)
                    if not word_text:
                        continue
                    cur_words.append(OcrWord(text=word_text, bbox=_box(vword.get("boundingBox", {})), conf=vword.get("confidence")))
                    cur_text.append(word_text)
                    brk = (symbols[-1].get("property", {}).get("detectedBreak", {}) or {}).get("type") if symbols else None
                    if brk == "HYPHEN":
                        cur_text.append("-")
                    if brk in _LINE_END_BREAKS:
                        flush()
                    elif brk in _SPACE_BREAKS:
                        cur_text.append(" ")
                # A Vision paragraph always ends a line.
                flush()
            flush()
            if lines:
                page.blocks.append(OcrBlock(lines=lines, bbox=union_bbox([ln.bbox for ln in lines])))
        return page
