"""Document-aware chunking.

Book -> section -> paragraph -> (sentences only if needed). A paragraph stays intact unless it
is longer than MAX_CHARS; then it is split on sentence boundaries into consecutive, non-
overlapping slices (char_start/char_end into the paragraph), so every chunk's text is an exact
substring of the original paragraph and the full paragraph can always be shown.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_CHARS = 1400
TARGET_CHARS = 900

_SENTENCE_END = re.compile(r"(?<=[।?!॥؟۔])\s+|(?<=\.)\s+(?=[A-Zঀ-৿])")
_SOFT_BREAK = re.compile(r"(?<=[,;،:ঃ])\s+|\s+")


@dataclass
class ChunkSpec:
    chunk_index: int
    char_start: int
    char_end: int
    text: str


def _spans(text: str, pattern: re.Pattern) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in pattern.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if b > a]


def _pack(text: str, spans: list[tuple[int, int]], target: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for a, b in spans:
        if cur is None:
            cur = (a, b)
        elif b - cur[0] <= target:
            cur = (cur[0], b)
        else:
            out.append(cur)
            cur = (a, b)
    if cur:
        out.append(cur)
    return out


def split_paragraph(text: str, max_chars: int = MAX_CHARS, target: int = TARGET_CHARS) -> list[ChunkSpec]:
    if len(text) <= max_chars:
        return [ChunkSpec(0, 0, len(text), text)]
    pieces: list[tuple[int, int]] = []
    for a, b in _pack(text, _spans(text, _SENTENCE_END), target):
        if b - a <= max_chars:
            pieces.append((a, b))
        else:  # one enormous "sentence": fall back to soft breaks inside it
            sub = [(a + x, a + y) for x, y in _spans(text[a:b], _SOFT_BREAK)]
            pieces.extend(_pack(text, sub, target))
    # merge a tiny trailing piece into its predecessor
    if len(pieces) > 1 and pieces[-1][1] - pieces[-1][0] < 150:
        pieces[-2] = (pieces[-2][0], pieces[-1][1])
        pieces.pop()
    return [ChunkSpec(i, a, b, text[a:b]) for i, (a, b) in enumerate(pieces)]


def stable_id(prefix: str, *parts: object, length: int = 10) -> str:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:length]}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_embed_text(
    *,
    book_title: str,
    section: str | None,
    chapter: str | None,
    heading: str | None,
    text: str,
    prev_tail: str | None = None,
    next_head: str | None = None,
) -> str:
    """Contextualised text for the embedding (never shown to users).

    Adds the book/section/heading path and, for paragraphs that run across a page break, the
    adjoining part of the paragraph on the neighbouring page - so a half-paragraph still
    embeds with its full meaning.
    """
    path = " › ".join(x for x in (book_title, section, chapter, heading if heading != chapter else None) if x)
    parts = [path]
    if prev_tail:
        parts.append("…" + prev_tail)
    parts.append(text)
    if next_head:
        parts.append(next_head + "…")
    return "\n".join(parts)
