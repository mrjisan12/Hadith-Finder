"""Page layout analysis: running header, printed page number (footer), paragraphs, headings.

Designed around this book's scans (see docs/ARCHITECTURE.md):

* Running header in a box at the top:  "ফাযায়েলে কুরআন-৭৬"  (sub-book title + sub-book page)
* Printed book page number in a box at the bottom: "২৬৬"
* Justified Bangla prose; a new paragraph starts with a first-line indent, after a short
  (not full-width) line, after extra vertical space, or at a numbered hadith "(৩৬)".
* Arabic (right) / Urdu (left) text blocks, sometimes side by side.

Everything is heuristic but conservative: when unsure, lines stay in the same paragraph
(a slightly longer "exact paragraph" is harmless; a sentence split across two sources is not).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field

from app.core.textnorm import clean_display_text, detect_script, to_ascii_digits
from ingestion.ocr.base import OcrBlock, OcrLine, OcrPage, union_bbox

RTL = {"ar", "ur"}
_BOX_CHARS = "|[]{}()<>“”\"'`~_=+*•·.,:;!¡?¿।॥ \t-–—ـ"
_HEADER_RE = re.compile(r"^(?P<title>.*?[ঀ-৿A-Za-z].*?)\s*[-–—ـ:]?\s*(?P<num>[০-৯0-9]{1,4})$")
_FOOTER_RE = re.compile(r"^[০-৯0-9]{1,4}$")
_HADITH_START = re.compile(r"^[\(\[{]?\s*([০-৯0-9]{1,4})\s*[\)\]}]?\s*[।.:ঃ-]?\s+\S")
_TERMINAL = tuple("।?!॥.”\"')]}؟۔")
_CHAPTER_WORDS = ("পরিচ্ছেদ", "অধ্যায়", "অধ্যায়", "অনুচ্ছেদ", "ভূমিকা", "মুখবন্ধ", "উপসংহার", "পরিশিষ্ট", "মুকাদ্দমা", "খাতেমা")


@dataclass
class LayoutParagraph:
    index: int
    kind: str  # "text" | "heading"
    lang: str
    text: str
    bbox: list[float]  # normalised [x0, y0, x1, y1]
    line_boxes: list[list[float]]
    conf: float | None
    hadith_number: str | None = None
    starts_indented: bool = False
    ends_full_width: bool = False
    is_chapter_heading: bool = False


@dataclass
class PageLayout:
    pdf_page: int
    width: int
    height: int
    header_text: str | None = None
    header_title: str | None = None
    header_page: int | None = None
    footer_raw: str | None = None
    footer_number: int | None = None
    mean_conf: float | None = None
    paragraphs: list[LayoutParagraph] = field(default_factory=list)
    # tentative: last text paragraph looks unfinished (full-width last line, no terminal punctuation)
    ends_mid_paragraph: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PageLayout:
        paras = [LayoutParagraph(**p) for p in d.pop("paragraphs", [])]
        return cls(**d, paragraphs=paras)


# --------------------------------------------------------------------------- helpers
def _strip_box(text: str) -> str:
    return text.strip(_BOX_CHARS)


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _line_script(line: OcrLine) -> str:
    s = detect_script(line.text)
    return "bn" if s == "other" else s


def _join_lines(texts: list[str]) -> str:
    out = ""
    for t in texts:
        t = t.strip()
        if not out:
            out = t
        elif out.endswith(("-", "–")):
            out += t
        else:
            out += " " + t
    return clean_display_text(out)


def _order_blocks(blocks: list[OcrBlock], line_scripts: dict[int, str]) -> list[OcrBlock]:
    """Top-to-bottom rows of blocks; side-by-side blocks ordered right-to-left when RTL."""
    blocks = [b for b in blocks if b.lines]
    blocks.sort(key=lambda b: b.bbox[1])
    rows: list[list[OcrBlock]] = []
    for b in blocks:
        placed = False
        for row in rows:
            r0 = min(x.bbox[1] for x in row)
            r1 = max(x.bbox[3] for x in row)
            overlap = min(r1, b.bbox[3]) - max(r0, b.bbox[1])
            smaller = min(r1 - r0, b.bbox[3] - b.bbox[1]) or 1
            no_x_overlap = all(b.bbox[0] >= x.bbox[2] or b.bbox[2] <= x.bbox[0] for x in row)
            if overlap / smaller > 0.5 and no_x_overlap:
                row.append(b)
                placed = True
                break
        if not placed:
            rows.append([b])
    ordered: list[OcrBlock] = []
    for row in rows:
        rtl_votes = sum(1 for b in row for ln in b.lines if line_scripts[id(ln)] in RTL)
        rtl = rtl_votes > sum(len(b.lines) for b in row) / 2
        row.sort(key=lambda b: -b.bbox[2] if rtl else b.bbox[0])
        ordered.extend(row)
    return ordered


# --------------------------------------------------------------------------- main
def analyse_page(ocr: OcrPage, pdf_page: int) -> PageLayout:
    W, H = ocr.width or 1, ocr.height or 1
    layout = PageLayout(pdf_page=pdf_page, width=W, height=H, mean_conf=ocr.mean_conf)

    all_lines = [ln for ln in ocr.lines if ln.text.strip()]
    if not all_lines:
        return layout
    removed: set[int] = set()

    # ---------------------------------------------------------------- header
    top = sorted(all_lines, key=lambda ln: ln.y0)[0]
    if top.cy < 0.07 * H:
        band = [ln for ln in all_lines if top.y0 - 0.5 * top.height <= ln.cy <= top.y1 + 0.5 * top.height]
        band.sort(key=lambda ln: ln.x0)
        header_text = _strip_box(" ".join(_strip_box(ln.text) for ln in band))
        m = _HEADER_RE.match(header_text)
        band_w = max(ln.x1 for ln in band) - min(ln.x0 for ln in band)
        if m or band_w < 0.7 * W:
            layout.header_text = header_text
            if m:
                layout.header_title = _strip_box(m.group("title"))
                layout.header_page = int(to_ascii_digits(m.group("num")))
            else:
                layout.header_title = header_text or None
            removed.update(id(ln) for ln in band)

    # ---------------------------------------------------------------- footer
    # The printed page number sits centred in a box at the bottom. Some pages also carry a
    # printer's signature mark such as "—৩" at the bottom-left, often BELOW the box: ignore
    # dash-prefixed and off-centre numbers so it is never mistaken for the page number.
    footer_candidates = []
    for ln in all_lines:
        if ln.cy < 0.88 * H:
            continue
        raw = _strip_box(ln.text).replace(" ", "")
        if not _FOOTER_RE.match(raw):
            continue
        removed.add(id(ln))  # numeric furniture is never content
        cx = (ln.x0 + ln.x1) / 2
        if ln.text.strip().startswith(("-", "–", "—", "_")) or abs(cx - W / 2) > 0.2 * W:
            continue
        footer_candidates.append((abs(cx - W / 2), ln, raw))
    if footer_candidates:
        _, ln, raw = min(footer_candidates, key=lambda c: c[0])
        layout.footer_raw = ln.text
        layout.footer_number = int(to_ascii_digits(raw))

    # ---------------------------------------------------------------- noise
    for ln in all_lines:
        if not _has_letters(ln.text) and not _FOOTER_RE.match(_strip_box(ln.text).replace(" ", "")):
            removed.add(id(ln))

    content_blocks = []
    for b in ocr.blocks:
        kept = [ln for ln in b.lines if id(ln) not in removed and ln.text.strip()]
        if kept:
            content_blocks.append(OcrBlock(lines=sorted(kept, key=lambda ln: ln.y0), bbox=union_bbox([ln.bbox for ln in kept])))
    if not content_blocks:
        return layout

    scripts = {id(ln): _line_script(ln) for b in content_blocks for ln in b.lines}
    ordered_lines = [ln for b in _order_blocks(content_blocks, scripts) for ln in b.lines]

    # ---------------------------------------------------------------- page metrics (from LTR prose lines)
    ltr = [ln for ln in ordered_lines if scripts[id(ln)] not in RTL]
    heights = [ln.height for ln in ordered_lines if ln.height > 0]
    h = statistics.median(heights) if heights else H / 40
    if ltr:
        widest = max(ln.x1 - ln.x0 for ln in ltr)
        body = [ln for ln in ltr if (ln.x1 - ln.x0) >= 0.6 * widest] or ltr
        L = statistics.quantiles([ln.x0 for ln in body], n=20)[0] if len(body) >= 2 else body[0].x0
        R = statistics.quantiles([ln.x1 for ln in body], n=20)[-1] if len(body) >= 2 else body[0].x1
        gaps = [
            b.y0 - a.y1
            for a, b in zip(ltr, ltr[1:])
            if 0 <= b.y0 - a.y1 < 3 * h and a.block_index == b.block_index
        ]
        typical_gap = statistics.median(gaps) if gaps else 0.4 * h
    else:
        L, R, typical_gap = 0.05 * W, 0.95 * W, 0.4 * h
    col_w = max(R - L, 1)
    indent_thr = 0.9 * h
    short_thr = 1.6 * h
    gap_thr = typical_gap + 0.9 * h

    # ---------------------------------------------------------------- group lines into paragraphs
    groups: list[list[OcrLine]] = []
    for i, ln in enumerate(ordered_lines):
        script = scripts[id(ln)]
        if i == 0:
            groups.append([ln])
            continue
        prev = ordered_lines[i - 1]
        pscript = scripts[id(prev)]
        new = False
        if script != pscript and not (script in RTL and pscript in RTL):
            new = True
        elif script in RTL:
            new = ln.block_index != prev.block_index or (ln.y0 - prev.y1) > gap_thr
        else:
            gap = ln.y0 - prev.y1
            if gap > gap_thr or gap < -0.5 * h:  # extra space, or jumped back up (new column/block)
                new = True
            elif ln.x0 - L > indent_thr:
                new = True
            elif R - prev.x1 > short_thr:
                new = True
            elif _HADITH_START.match(ln.text.strip()):
                new = True
        if new:
            groups.append([ln])
        else:
            groups[-1].append(ln)

    # ---------------------------------------------------------------- build paragraphs
    paras: list[LayoutParagraph] = []
    for g in groups:
        text = _join_lines([ln.text for ln in g])
        if not text:
            continue
        lang = scripts[id(g[0])]
        box = union_bbox([ln.bbox for ln in g])
        confs = [ln.conf for ln in g if ln.conf is not None]
        width = box[2] - box[0]
        centre_off = abs((box[0] + box[2]) / 2 - (L + R) / 2)
        is_heading = (
            lang not in RTL
            and len(g) <= 2
            and len(text) <= 80
            and width < 0.7 * col_w
            and centre_off < 0.12 * col_w
            and not text.endswith(("।", "?", "!"))
            and not (text.startswith("(") and text.endswith(")"))
        )
        m = _HADITH_START.match(text)
        paras.append(
            LayoutParagraph(
                index=0,
                kind="heading" if is_heading else "text",
                lang=lang,
                text=text,
                bbox=[round(box[0] / W, 5), round(box[1] / H, 5), round(box[2] / W, 5), round(box[3] / H, 5)],
                line_boxes=[[round(ln.x0 / W, 5), round(ln.y0 / H, 5), round(ln.x1 / W, 5), round(ln.y1 / H, 5)] for ln in g],
                conf=round(sum(confs) / len(confs), 4) if confs else None,
                hadith_number=to_ascii_digits(m.group(1)) if m and not is_heading else None,
                starts_indented=(g[0].x0 - L) > indent_thr,
                ends_full_width=(R - g[-1].x1) <= short_thr,
                is_chapter_heading=is_heading and any(w in text for w in _CHAPTER_WORDS),
            )
        )

    paras = _merge_fragments(paras)
    for i, p in enumerate(paras):
        p.index = i
    layout.paragraphs = paras

    last_text = next((p for p in reversed(paras) if p.kind == "text" and p.lang not in RTL), None)
    layout.ends_mid_paragraph = bool(
        last_text is not None
        and last_text is paras[-1]
        and last_text.ends_full_width
        and not last_text.text.rstrip().endswith(_TERMINAL)
    )
    return layout


def _merge_fragments(paras: list[LayoutParagraph]) -> list[LayoutParagraph]:
    """Attach attribution lines "(তাবারানী)" to the previous paragraph; tiny fragments to a neighbour."""

    def merge(into: LayoutParagraph, other: LayoutParagraph, append: bool) -> None:
        into.text = _join_lines([into.text, other.text] if append else [other.text, into.text])
        into.line_boxes = into.line_boxes + other.line_boxes if append else other.line_boxes + into.line_boxes
        into.bbox = [
            min(into.bbox[0], other.bbox[0]),
            min(into.bbox[1], other.bbox[1]),
            max(into.bbox[2], other.bbox[2]),
            max(into.bbox[3], other.bbox[3]),
        ]
        if not append:
            into.starts_indented = other.starts_indented
            into.hadith_number = other.hadith_number or into.hadith_number
        else:
            into.ends_full_width = other.ends_full_width

    out: list[LayoutParagraph] = []
    pending_prefix: LayoutParagraph | None = None
    for p in paras:
        if pending_prefix is not None:
            if pending_prefix.lang == p.lang and p.kind == "text":
                merge(p, pending_prefix, append=False)
            else:
                out.append(pending_prefix)
            pending_prefix = None

        stripped = p.text.strip()
        is_attribution = stripped.startswith(("(", "[")) and stripped.endswith((")", "]")) and len(stripped) <= 120
        if is_attribution and out and out[-1].kind == "text" and out[-1].lang == p.lang:
            merge(out[-1], p, append=True)
            continue
        if p.kind == "text" and len(stripped) < 15:
            pending_prefix = p
            continue
        out.append(p)
    if pending_prefix is not None:
        if out and out[-1].lang == pending_prefix.lang and out[-1].kind == "text":
            merge(out[-1], pending_prefix, append=True)
        else:
            out.append(pending_prefix)
    return out
