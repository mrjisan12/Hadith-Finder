from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.schemas.source import SourceOut

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)

    @field_validator("content")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _CONTROL.sub("", v).strip()


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="The user's question (Bangla, English, ...)")
    book_id: int | None = Field(default=None, description="Restrict search to one book; all books when omitted")
    history: list[HistoryTurn] = Field(default_factory=list, max_length=12)
    debug: bool = Field(default=False, description="Include retrieval diagnostics (only if ENABLE_DEBUG=true)")

    @field_validator("query")
    @classmethod
    def _clean_query(cls, v: str) -> str:
        v = _CONTROL.sub("", v).strip()
        if not v:
            raise ValueError("query must not be empty")
        if len(v) > settings.max_query_chars:
            raise ValueError(f"query is longer than {settings.max_query_chars} characters")
        return v


class ChatResponse(BaseModel):
    answer: str
    insufficient_evidence: bool
    sources: list[SourceOut]
    query_id: int | None = None
    debug: dict | None = None
