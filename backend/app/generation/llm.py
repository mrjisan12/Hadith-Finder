"""LLM client abstraction.

* anthropic (default) - official Anthropic SDK. Uses structured outputs for JSON tasks,
  adaptive thinking (the model default) with an `effort` level, and server-side refusal
  fallbacks on models that support them.
* openai - official OpenAI SDK; also covers OpenAI-compatible APIs (Gemini, Groq, OpenRouter,
  DeepSeek, ...) through LLM_BASE_URL.

The LLM is only used for query understanding, reranking and writing the answer. It is never
the source of quoted text: quotations come from the database (see app.citation).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("llm")

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5", "claude-fable-5-1"}


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class LLMClient(Protocol):
    async def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 8000) -> dict: ...

    def stream_answer(self, *, system: str, messages: list[dict], max_tokens: int) -> AsyncIterator[str]: ...


# =========================================================================== Anthropic
class AnthropicLLM:
    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        # api_key=None lets the SDK fall back to ANTHROPIC_API_KEY / an `ant auth login` profile.
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.llm_api_key or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )

    @staticmethod
    def _output_config(model: str, effort: str, extra: dict | None = None) -> dict | None:
        cfg = dict(extra or {})
        if effort and not model.startswith("claude-haiku"):  # Haiku 4.5 rejects `effort`
            cfg["effort"] = effort
        return cfg or None

    def _create_kwargs(self, model: str) -> dict:
        if settings.llm_refusal_fallback and model in _FALLBACK_MODELS:
            return {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
        return {}

    def _messages_api(self, model: str):
        return self.client.beta.messages if self._create_kwargs(model) else self.client.messages

    async def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 8000) -> dict:
        model = settings.fast_model
        params = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=self._output_config(
                model, settings.llm_fast_effort, {"format": {"type": "json_schema", "schema": schema}}
            ),
            **self._create_kwargs(model),
        )
        try:
            resp = await self._messages_api(model).create(**params)
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code} (request {exc.request_id})") from exc
        except self._anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API") from exc
        if resp.stop_reason == "refusal":
            raise LLMRefusal("The model declined this request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON (stop_reason={resp.stop_reason})") from exc

    async def stream_answer(self, *, system: str, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        model = settings.llm_model
        params = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **self._create_kwargs(model),
        )
        output_config = self._output_config(model, settings.llm_answer_effort)
        if output_config:
            params["output_config"] = output_config
        try:
            async with self._messages_api(model).stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code} (request {exc.request_id})") from exc
        except self._anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API") from exc
        if final.stop_reason == "refusal":
            raise LLMRefusal("The model declined this request")
        if final.stop_reason == "max_tokens":
            log.warning("answer truncated at max_tokens")


# =========================================================================== OpenAI(-compatible)
class OpenAILLM:
    def __init__(self) -> None:
        import openai

        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set")
        self._openai = openai
        self.client = openai.AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )

    async def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 8000) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        try:
            try:
                resp = await self.client.chat.completions.create(
                    model=settings.fast_model,
                    messages=messages,
                    response_format={"type": "json_schema", "json_schema": {"name": "result", "schema": schema}},
                )
            except self._openai.BadRequestError:
                # Some OpenAI-compatible providers only support JSON mode.
                messages[0]["content"] += "\n\nReply with a single JSON object matching this schema:\n" + json.dumps(schema)
                resp = await self.client.chat.completions.create(
                    model=settings.fast_model, messages=messages, response_format={"type": "json_object"}
                )
        except self._openai.APIError as exc:
            raise LLMError(f"LLM API error: {type(exc).__name__}") from exc
        text = resp.choices[0].message.content or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Model returned invalid JSON") from exc

    async def stream_answer(self, *, system: str, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        try:
            stream = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "system", "content": system}, *messages],
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except self._openai.APIError as exc:
            raise LLMError(f"LLM API error: {type(exc).__name__}") from exc


@lru_cache
def get_llm() -> LLMClient:
    if settings.llm_provider == "openai":
        return OpenAILLM()
    return AnthropicLLM()
