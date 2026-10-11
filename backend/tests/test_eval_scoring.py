from app.schemas.source import PagePart, SourceOut
from eval.run_eval import score_item, snippet_in


def src(pdf_page, printed, text, **kw):
    return SourceOut(
        source_id="chunk_aaaaaaaaaa", paragraph_id="para_aaaaaaaaaa", book_id=1, book="B", book_native=None,
        page_id=1, pdf_page=pdf_page, printed_page=printed, printed_page_label=str(printed), printed_page_source="ocr",
        original_text=text, matched_text=text, match_start=0, match_end=len(text), lang="bn", page_image_url="/x", **kw,
    )


def test_snippet_matching_tolerates_spelling_variants():
    assert snippet_in("নামাজ পড়িতে", "হে বৎস! নামায পড়িতে থাক")
    assert not snippet_in("রোযা রাখিবে", "হে বৎস! নামায পড়িতে থাক")


def test_score_item_rank_paragraph_and_printed_page():
    item = {"expected": [{"pdf_page": 263, "printed_page": 266, "snippet": "তিন ব্যক্তি"}]}
    sources = [src(10, 13, "অন্য বিষয়"), src(263, 266, "তিন ব্যক্তি এমন হইবে")]
    r = score_item(item, sources)
    assert r == {"first_rank": 2, "paragraph_rank": 2, "printed_ok": True}


def test_score_item_counts_continuation_page_and_wrong_printed():
    item = {"expected": [{"pdf_page": 264, "printed_page": 267, "snippet": "শেষ অংশ"}]}
    cont = PagePart(text="শেষ অংশ এখানে", page_id=2, pdf_page=264, printed_page=267, printed_page_label="267", page_image_url="/y")
    r = score_item(item, [src(263, 265, "প্রথম অংশ", continuation=cont)])
    assert r["first_rank"] == 1 and r["paragraph_rank"] == 1 and r["printed_ok"] is None
