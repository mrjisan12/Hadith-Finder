from app.citation.verify import extract_citations, sanitize_answer
from app.retrieval.fusion import rrf_fuse
from app.retrieval.search import Hit
from ingestion.chunking import split_paragraph, stable_id

A, B, C = "chunk_aaaaaaaaaa", "chunk_bbbbbbbbbb", "chunk_cccccccccc"


def test_short_paragraph_stays_intact():
    text = "হযরত ইবনে ওমর (রাযিঃ) হইতে বর্ণিত। " * 5
    chunks = split_paragraph(text)
    assert len(chunks) == 1 and chunks[0].text == text


def test_long_paragraph_split_into_exact_contiguous_slices():
    sentence = "ইহা একটি দীর্ঘ বাক্য যাহা পরীক্ষার জন্য লেখা হইয়াছে। "
    text = (sentence * 80).strip()
    chunks = split_paragraph(text)
    assert len(chunks) > 1
    for ch in chunks:
        assert text[ch.char_start : ch.char_end] == ch.text
        assert len(ch.text) <= 1400
    # coverage: nothing lost except the whitespace between slices
    joined = "".join(text[c.char_start : c.char_end] for c in chunks)
    assert joined.replace(" ", "") == text.replace(" ", "")


def test_stable_ids_are_deterministic():
    assert stable_id("chunk", "fazail-e-amal", 263, 4, 0) == stable_id("chunk", "fazail-e-amal", 263, 4, 0)
    assert stable_id("chunk", "fazail-e-amal", 263, 4, 0) != stable_id("chunk", "fazail-e-amal", 263, 4, 1)
    assert len(stable_id("chunk", "x")) == len("chunk_") + 10


def test_sanitize_removes_fabricated_citations():
    answer = f"সদকা আগুন নিভিয়ে দেয় [{A}]। আরেকটি বর্ণনা [{B}, {C}]। ভুল সূত্র [chunk_ffffffffff]।"
    clean, cited, rejected = sanitize_answer(answer, {A, B})
    assert cited == [A, B]
    assert rejected == [C, "chunk_ffffffffff"]
    assert "chunk_ffffffffff" not in clean and C not in clean
    assert f"[{B}]" in clean


def test_sanitize_wraps_bare_ids_and_keeps_normal_brackets():
    clean, cited, _ = sanitize_answer(f"দেখুন {A} এবং [টীকা]", {A})
    assert f"[{A}]" in clean and "[টীকা]" in clean and cited == [A]


def test_extract_citations_order():
    assert extract_citations(f"x [{B}] y [{A}][{B}]") == [B, A]


def test_rrf_rewards_agreement_between_retrievers():
    lists = {
        "vec": [Hit(1, 0.9), Hit(2, 0.8), Hit(3, 0.7)],
        "fts": [Hit(3, 5.0), Hit(4, 4.0)],
    }
    fused = rrf_fuse(lists)
    assert fused[0].chunk_id == 3  # found by both
    assert fused[0].ranks == {"vec": 3, "fts": 1}
