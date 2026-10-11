"""Answer synthesis from retrieved passages (streaming)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import settings
from app.generation.llm import get_llm
from app.generation.prompts import ANSWER_SYSTEM, INSUFFICIENT_MARKER, answer_user_message
from app.retrieval.hybrid import Selected

MESSAGES = {
    "insufficient": {
        "bn": "দুঃখিত, কিতাবের যে অংশগুলো খুঁজে পাওয়া গেছে তাতে এই প্রশ্নের উত্তর দেওয়ার মতো যথেষ্ট তথ্য নেই। "
        "অনুগ্রহ করে প্রশ্নটি অন্যভাবে বা আরও নির্দিষ্ট করে জিজ্ঞাসা করুন।",
        "en": "The passages I could find in the book do not contain enough evidence to answer this question. "
        "Please try rephrasing it or asking more specifically.",
    },
    "out_of_scope": {
        "bn": "আমি শুধু ফাযায়েলে আমল কিতাব থেকে উৎসসহ উত্তর দিই। কিতাবের কোনো বিষয়ে প্রশ্ন করুন — "
        "যেমন: “সদকার ফজিলত সম্পর্কে কী বলা হয়েছে?”",
        "en": "I answer questions from the book Fazail-e-Amal, with the original passage and page for every answer. "
        "Ask about a topic in the book - for example: “What does the book say about the virtue of charity?”",
    },
    "llm_failed": {
        "bn": "উত্তর তৈরি করা সম্ভব হয়নি। নিচে কিতাবের প্রাসঙ্গিক মূল অংশগুলো দেখুন।",
        "en": "The answer could not be generated. The relevant original passages from the book are shown below.",
    },
}


def message(kind: str, language: str) -> str:
    return MESSAGES[kind]["bn" if language == "bn" else "en"]


def build_answer_messages(question: str, standalone: str, selected: list[Selected]) -> list[dict]:
    sources = [
        {
            "source_id": s.source.source_id,
            "section": " › ".join(x for x in (s.source.section, s.source.chapter) if x),
            "printed_page_label": s.source.printed_page_label,
            "pdf_page": s.source.pdf_page,
            "context_text": s.context_text,
        }
        for s in selected
    ]
    return [{"role": "user", "content": answer_user_message(question, standalone, sources)}]


async def stream_answer(question: str, standalone: str, selected: list[Selected]) -> AsyncIterator[str]:
    async for delta in get_llm().stream_answer(
        system=ANSWER_SYSTEM,
        messages=build_answer_messages(question, standalone, selected),
        max_tokens=settings.llm_max_answer_tokens,
    ):
        yield delta


def split_insufficient(answer: str) -> tuple[bool, str]:
    text = answer.strip()
    if text.startswith(INSUFFICIENT_MARKER):
        return True, text[len(INSUFFICIENT_MARKER):].strip()
    if INSUFFICIENT_MARKER in text:
        return True, text.replace(INSUFFICIENT_MARKER, "").strip()
    return False, text
