from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import chat_events, chat_once

router = APIRouter(tags=["chat"])
log = get_logger("api.chat")


@router.post("/chat", response_model=ChatResponse, summary="Ask a question (complete JSON response)")
@limiter.limit(settings.rate_limit_chat)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Retrieve, rerank and answer. `sources[].original_text` is always read from the database."""
    return await chat_once(body)


@router.post(
    "/chat/stream",
    summary="Ask a question (Server-Sent Events)",
    response_description="text/event-stream of JSON events: status | sources | delta | final | error",
)
@limiter.limit(settings.rate_limit_chat)
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    async def gen():
        try:
            async for event in chat_events(body):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            log.exception("chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'internal_error'})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
