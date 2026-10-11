from app.core.textnorm import (
    clean_display_text,
    detect_script,
    fold_tokens,
    query_terms,
    search_key,
    to_ascii_digits,
    to_bangla_digits,
    to_tsquery_expr,
)


def same(a: str, b: str) -> bool:
    return fold_tokens(a) == fold_tokens(b)


def test_modern_and_book_spellings_fold_together():
    assert same("সদকার ফজিলত", "ছদকার ফযীলত")
    assert same("নামাজ", "নামাযের")
    assert same("যাকাত", "জাকাত")
    assert same("কুরআন", "কোরআনের")
    assert same("আল্লাহ", "আল্লাহর")
    assert same("উমর", "ওমর")


def test_nukta_forms_are_equivalent():
    precomposed = "য়"  # য়
    decomposed = "য়"  # য + nukta
    assert fold_tokens(f"বিষ{precomposed}") == fold_tokens(f"বিষ{decomposed}")


def test_arabic_diacritics_ignored():
    assert same("صَدَقَة", "صدقة")


def test_query_terms_drop_stopwords():
    assert query_terms("সদকার ফজিলত সম্পর্কে কী বলা হয়েছে?") == ["sdka", "fjilt"]


def test_tsquery_is_always_safe():
    expr = to_tsquery_expr(["abc'); drop table x;--", "sdka", "fj"])
    assert set(expr) <= set("abcdefghijklmnopqrstuvwxyz0123456789 |:*")
    assert "sdka:*" in expr


def test_search_key_is_ascii():
    key = search_key("হযরত ইবনে ওমর (রাযিঃ) হইতে বর্ণিত — صدقة 123")
    assert key.isascii()


def test_digits():
    assert to_ascii_digits("২৬৬") == "266"
    assert to_bangla_digits(608) == "৬০৮"


def test_detect_script():
    assert detect_script("হযরত ইবনে ওমর") == "bn"
    assert detect_script("لَا يَهُولُهُمُ الْفَزَعُ") == "ar"
    assert detect_script("ہیں جن کو قیامت کا خوف") == "ur"
    assert detect_script("charity") == "en"


def test_clean_display_text_keeps_letters():
    raw = "হযরত  ইবনে​ ওমর "
    assert clean_display_text(raw) == "হযরত ইবনে ওমর"
