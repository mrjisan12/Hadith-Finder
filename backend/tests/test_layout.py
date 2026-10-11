"""Layout analysis on a synthetic page shaped like the scans (2400 x 3700 px OCR render)."""

from ingestion.layout import analyse_page
from ingestion.ocr.base import OcrBlock, OcrLine, OcrPage, OcrWord
from ingestion.ocr.google_vision import GoogleVisionOcr

W, H = 2400, 3700
L, R = 200, 2200


def line(text, x0, y0, x1, h=60, block=0):
    return OcrLine(words=[OcrWord(text, (x0, y0, x1, y0 + h), 0.95)], text=text, bbox=(x0, y0, x1, y0 + h), conf=0.95, block_index=block)


def block(*lines):
    xs0, ys0 = min(ln.x0 for ln in lines), min(ln.y0 for ln in lines)
    xs1, ys1 = max(ln.x1 for ln in lines), max(ln.y1 for ln in lines)
    return OcrBlock(lines=list(lines), bbox=(xs0, ys0, xs1, ys1))


def build_page() -> OcrPage:
    y = iter(range(200, 4000, 90))
    header = block(line("ফাযায়েলে কুরআন-৭৬", 850, 50, 1550, block=0))
    p1 = block(
        line("এই আয়াতে কয়েকটি গুরুত্বপূর্ণ বিষয় উল্লেখ করা হইয়াছে যাহা", L + 90, next(y), R, block=1),
        line("প্রকৃতপক্ষে এই বিষয়গুলি গুরুত্বপূর্ণ এবং যাবতীয় কামিয়াবীর", L, next(y), R, block=1),
        line("চাবিকাঠি।", L, next(y), 700, block=1),
    )
    y_ar = next(y)
    arabic = block(
        line("لَا يَهُولُهُمُ الْفَزَعُ الْأَكْبَرُ", 1300, y_ar, R, block=2),
        line("وَلَا يَنَالُهُمُ الْحِسَابُ", 1300, next(y), R, block=2),
    )
    p2 = block(
        line("(৩৬) হযরত ইবনে ওমর (রাযিঃ) হইতে বর্ণিত, হুযূর সাল্লাল্লাহু", L, next(y) + 40, R, block=3),
        line("আলাইহি ওয়াসাল্লাম এরশাদ করিয়াছেন, তিন ব্যক্তি এমন হইবে", L, next(y) + 40, R, block=3),
        line("যাহারা ভীত হইবে না।", L, next(y) + 40, 900, block=3),
        line("(তাবারানী)", 1700, next(y) + 40, R, block=3),
    )
    heading = block(line("দ্বিতীয় পরিচ্ছেদ", 950, next(y) + 80, 1450, block=4))
    p3 = block(
        line("কিয়ামতের দিনের কঠিন অবস্থা, ভয়াবহতা ও মুসীবত এমন নয় যে,", L + 90, next(y) + 120, R, block=5),
        line("কোন মুসলমানের অন্তর উহা হইতে খালি বা বে-খবর থাকিতে", L, next(y) + 120, R, block=5),
    )
    footer = block(line("২৬৬", 1120, 3560, 1280, block=6))
    signature = block(line("—৩", 40, 3640, 120, block=7))  # printer's mark below the page-number box
    return OcrPage(width=W, height=H, engine="test", blocks=[header, p1, arabic, p2, heading, p3, footer, signature])


def test_header_footer_and_paragraphs():
    lay = analyse_page(build_page(), pdf_page=263)
    assert lay.header_title == "ফাযায়েলে কুরআন"
    assert lay.header_page == 76
    assert lay.footer_number == 266

    kinds = [(p.kind, p.lang) for p in lay.paragraphs]
    assert kinds == [("text", "bn"), ("text", "ar"), ("text", "bn"), ("heading", "bn"), ("text", "bn")]

    p1, ar, p2, head, p3 = lay.paragraphs
    assert p1.text.endswith("চাবিকাঠি।") and p1.starts_indented
    assert p2.hadith_number == "36"
    assert p2.text.endswith("(তাবারানী)")  # attribution merged into its paragraph
    assert head.is_chapter_heading
    assert "২৬৬" not in " ".join(p.text for p in lay.paragraphs)  # footer not in content
    assert "ফাযায়েলে কুরআন-৭৬" not in " ".join(p.text for p in lay.paragraphs)
    assert all(0 <= v <= 1 for p in lay.paragraphs for v in p.bbox)
    assert lay.ends_mid_paragraph  # last paragraph runs to the right margin without a full stop


def test_vision_response_parsing():
    def word(text, x0, brk=None):
        sym = [{"text": ch} for ch in text]
        if brk:
            sym[-1]["property"] = {"detectedBreak": {"type": brk}}
        return {"symbols": sym, "confidence": 0.9, "boundingBox": {"vertices": [{"x": x0, "y": 10}, {"x": x0 + 50}, {"x": x0 + 50, "y": 40}, {"y": 40}]}}

    resp = {
        "fullTextAnnotation": {
            "pages": [
                {
                    "width": 1000,
                    "height": 1500,
                    "blocks": [
                        {"paragraphs": [{"words": [word("হিসাব", 0, "HYPHEN"), word("কিতাব", 60, "SPACE"), word("শেষ", 120, "LINE_BREAK")]}]}
                    ],
                }
            ]
        }
    }
    page = GoogleVisionOcr.parse(resp)
    assert [ln.text for ln in page.lines] == ["হিসাব-", "কিতাব শেষ"]
    assert page.lines[0].bbox[0] == 0 and page.width == 1000
