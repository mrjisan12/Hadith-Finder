"""Text normalisation for Bangla / Arabic / Urdu search.

Two separate concerns:

1. `clean_display_text` - light, lossless-in-meaning cleanup of OCR text that is SHOWN to users
   (Unicode NFC, whitespace). It never changes letters.

2. `search_key` / `query_terms` - an aggressive, *search-only* folding that maps Bangla and
   Arabic script onto a small ASCII phonetic alphabet. It is never displayed. It solves two
   real problems with this book:

   * Spelling variation of Arabic-origin words. The book writes "ফযীলত", "ছদকা", "নামায";
     users type "ফজিলত", "সদকা", "নামাজ". Folding য/জ, ী/ি, ূ/ু, শ/ষ/স/ছ, ণ/ন ... makes them equal.
   * PostgreSQL full-text / trigram behaviour on Bengali depends on the server locale (vowel
     signs can be treated as word separators). ASCII keys behave identically everywhere,
     including Supabase.

The same function is applied to indexed text and to queries, so folding is symmetric.
"""

from __future__ import annotations

import re
import unicodedata

# ----------------------------------------------------------------------------- digits
BN_DIGITS = "০১২৩৪৫৬৭৮৯"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_TABLE = {ord(c): str(i) for digits in (BN_DIGITS, AR_DIGITS, FA_DIGITS) for i, c in enumerate(digits)}


def to_ascii_digits(s: str) -> str:
    return s.translate(_DIGIT_TABLE)


def to_bangla_digits(n: int | str) -> str:
    return "".join(BN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(n))


# ----------------------------------------------------------------------------- scripts
_BN = re.compile(r"[ঀ-৿]")
_AR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")
# Letters used in Urdu but not in Arabic.
_URDU_ONLY = set("ٹڈڑںےۓھہۃگچپژ")


def detect_script(text: str) -> str:
    """Return 'bn', 'ar', 'ur', 'en' or 'other' by majority of letters."""
    bn = len(_BN.findall(text))
    ar = len(_AR.findall(text))
    en = len(_LATIN.findall(text))
    if max(bn, ar, en) == 0:
        return "other"
    if bn >= ar and bn >= en:
        return "bn"
    if ar >= en:
        return "ur" if any(c in _URDU_ONLY for c in text) else "ar"
    return "en"


# ----------------------------------------------------------------------------- display cleanup
_ZW = re.compile(r"[​‎‏﻿]")  # keep ZWJ/ZWNJ (‌ ‍): they affect Bangla shaping
_SPACES = re.compile(r"[ \t  - 　]+")


def clean_display_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _ZW.sub("", text)
    text = _SPACES.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


# ----------------------------------------------------------------------------- search folding
NUKTA = "়"

_BN_MAP: dict[str, str] = {
    # independent vowels
    "অ": "a", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u", "ঊ": "u", "ঋ": "ri", "ৠ": "ri",
    "এ": "e", "ঐ": "oi", "ও": "u", "ঔ": "u",  # ও/উ fold: কোরআন/কুরআন, ওমর/উমর
    # vowel signs
    "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u", "ৃ": "ri", "ৄ": "ri",
    "ে": "e", "ৈ": "oi", "ো": "u", "ৌ": "u", "ৗ": "u",
    # consonants (folded)
    "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "ng",
    "চ": "c", "ছ": "s", "জ": "j", "ঝ": "jh", "ঞ": "n",
    "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh", "ণ": "n",
    "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n",
    "প": "p", "ফ": "f", "ব": "b", "ভ": "bh", "ম": "m",
    "য": "j", "র": "r", "ল": "l", "শ": "s", "ষ": "s", "স": "s", "হ": "h",
    "ড়": "r", "ঢ়": "r", "য়": "y", "ৎ": "t", "ং": "ng", "ঃ": "h", "ঁ": "", "্": "", "ৰ": "r", "ৱ": "w",
    # rare / misc
    "ঽ": "", "৺": "",
}
# consonant + nukta combinations (NFC keeps these decomposed)
_BN_NUKTA_MAP = {"ড": "r", "ঢ": "r", "য": "y"}

_AR_MAP: dict[str, str] = {
    "ا": "a", "أ": "a", "إ": "i", "آ": "a", "ٱ": "a", "ء": "", "ؤ": "u", "ئ": "i",
    "ب": "b", "ت": "t", "ث": "s", "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "j",
    "ر": "r", "ز": "j", "س": "s", "ش": "s", "ص": "s", "ض": "d", "ط": "t", "ظ": "j",
    "ع": "", "غ": "g", "ف": "f", "ق": "k", "ك": "k", "ک": "k", "ل": "l", "م": "m",
    "ن": "n", "ه": "h", "ة": "h", "ہ": "h", "ۃ": "h", "ھ": "h", "و": "w",
    "ي": "y", "ی": "y", "ى": "y", "ے": "y", "ۓ": "y",
    "ٹ": "t", "ڈ": "d", "ڑ": "r", "ں": "n", "گ": "g", "چ": "c", "پ": "p", "ژ": "j",
}
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

# Common inflectional suffixes, already in folded form. Longest first; only one is stripped.
_SUFFIXES = sorted(
    [
        "digke", "diger", "gulor", "gulir", "gulo", "guli", "sumuh", "der", "era", "er",
        "ke", "te", "ra", "ti", "ta", "r", "e", "y",
    ],
    key=len,
    reverse=True,
)
_MIN_STEM = 3

# Query words carrying no topical meaning (Bangla chalit + sadhu + English). Folded at import.
_STOPWORDS_RAW = """
কী কি কে কেন কোন কোনো কিভাবে কীভাবে কেমন কোথায় কখন কত কতটা
সম্পর্কে সম্বন্ধে বিষয়ে ব্যাপারে বলা বলে বলেছে বলেছেন বলা হয়েছে হয়েছে হইয়াছে বলিয়াছেন
আছে আছেন রয়েছে হয় হয়ে হবে হইবে হইতে করে করা করিয়া করিতে করেন করিবে ছিল ছিলেন
এবং ও আর বা কিংবা অথবা যে যা যাহা যিনি তিনি তাহা তা সে এই ঐ উহা ইহা এর এরা তার তাহার তাদের
একটি একজন এক জন দিয়ে দিয়া থেকে হতে জন্য জন্যে নিয়ে নিয়া মধ্যে উপর সাথে সহিত প্রতি
আমাকে আমার আমি আমরা আমাদের তুমি আপনি আপনার বলুন বলো বলেন জানতে চাই চাই দয়া করে
বইয়ে বইতে কিতাবে গ্রন্থে বইটিতে এখানে সেখানে
what is are was were the a an of in on about for to and or does do how why which who say says said
book tell me please explain
"""


def _fold_char_seq(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if nxt == NUKTA and ch in _BN_NUKTA_MAP:
            out.append(_BN_NUKTA_MAP[ch])
            i += 2
            continue
        if ch == NUKTA:
            i += 1
            continue
        if ch in _BN_MAP:
            out.append(_BN_MAP[ch])
        elif ch in _AR_MAP:
            out.append(_AR_MAP[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch.lower())
        else:
            out.append(" ")
        i += 1
    return "".join(out)


def _stem(token: str) -> str:
    if token.isdigit():
        return token
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= _MIN_STEM:
            return token[: -len(suf)]
    return token


def _collapse(token: str) -> str:
    # doubled letters from gemination (আল্লাহ -> allah, সুন্নাত/সুন্নত) - collapse runs
    return re.sub(r"(.)\1+", r"\1", token)


def fold_tokens(text: str, stem: bool = True) -> list[str]:
    """Fold arbitrary Bangla/Arabic/English text into normalised ASCII tokens."""
    if not text:
        return []
    text = unicodedata.normalize("NFC", text)
    text = to_ascii_digits(text)
    text = _AR_DIACRITICS.sub("", text)
    folded = _fold_char_seq(text)
    tokens = []
    for tok in folded.split():
        tok = _collapse(tok)
        if stem:
            tok = _stem(tok)
        if tok:
            tokens.append(tok)
    return tokens


def search_key(text: str) -> str:
    """Folded ASCII representation stored in `chunks.search_text` (indexed for FTS + trigram)."""
    return " ".join(fold_tokens(text))


STOPWORDS: frozenset[str] = frozenset(fold_tokens(_STOPWORDS_RAW))


def query_terms(text: str) -> list[str]:
    """Distinct content terms for keyword search, in order of appearance."""
    seen: dict[str, None] = {}
    for tok in fold_tokens(text):
        if tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        seen.setdefault(tok, None)
    return list(seen)


_TSQUERY_SAFE = re.compile(r"[^a-z0-9]")


def to_tsquery_expr(terms: list[str], prefix: bool = True) -> str:
    """Build an OR tsquery string from folded terms. Output only contains [a-z0-9 |:*]."""
    parts = []
    for t in terms:
        t = _TSQUERY_SAFE.sub("", t)
        if not t:
            continue
        parts.append(f"{t}:*" if prefix and len(t) >= 3 else t)
    return " | ".join(dict.fromkeys(parts))
