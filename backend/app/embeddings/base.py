"""Embedding providers behind one interface. Swap via EMBEDDING_PROVIDER in .env.

All providers return L2-normalised float vectors of length EMBEDDING_DIM, and distinguish
document vs query inputs where the provider supports asymmetric retrieval.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Literal, Protocol

import httpx
import numpy as np
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings

InputType = Literal["document", "query"]


class EmbeddingProvider(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


def _normalise(vectors: list[list[float]], dim: int) -> list[list[float]]:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != dim:
        raise ValueError(f"Embedding dimension mismatch: got {arr.shape}, expected (*, {dim}). Check EMBEDDING_DIM.")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


_retry = retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, max=60),
    reraise=True,
)


class _HttpProvider:
    max_batch = 64

    def __init__(self) -> None:
        if not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_API_KEY is not set.")
        self.model = settings.resolved_embedding_model
        self.dim = settings.embedding_dim
        self._client = httpx.Client(timeout=120)

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch):
            out.extend(self._embed_batch(texts[i : i + self.max_batch], input_type))
        return _normalise(out, self.dim)

    def _embed_batch(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        raise NotImplementedError


class GeminiEmbeddings(_HttpProvider):
    """Google gemini-embedding-001 (strong multilingual incl. Bangla/Arabic; Matryoshka dims)."""

    max_batch = 100

    @_retry
    def _embed_batch(self, texts, input_type):
        task = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"
        model = self.model if self.model.startswith("models/") else f"models/{self.model}"
        body = {
            "requests": [
                {
                    "model": model,
                    "content": {"parts": [{"text": t}]},
                    "taskType": task,
                    "outputDimensionality": self.dim,
                }
                for t in texts
            ]
        }
        base = settings.embedding_base_url or "https://generativelanguage.googleapis.com/v1beta"
        resp = self._client.post(
            f"{base}/{model}:batchEmbedContents",
            json=body,
            headers={"x-goog-api-key": settings.embedding_api_key},
        )
        resp.raise_for_status()
        return [e["values"] for e in resp.json()["embeddings"]]


class CohereEmbeddings(_HttpProvider):
    """Cohere embed-multilingual-v3.0 (1024-d)."""

    max_batch = 96

    @_retry
    def _embed_batch(self, texts, input_type):
        base = settings.embedding_base_url or "https://api.cohere.com"
        resp = self._client.post(
            f"{base}/v2/embed",
            json={
                "model": self.model,
                "texts": texts,
                "input_type": "search_query" if input_type == "query" else "search_document",
                "embedding_types": ["float"],
            },
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]["float"]


class VoyageEmbeddings(_HttpProvider):
    """Voyage AI (voyage-3.5 / voyage-3-large; multilingual)."""

    max_batch = 64

    @_retry
    def _embed_batch(self, texts, input_type):
        base = settings.embedding_base_url or "https://api.voyageai.com"
        resp = self._client.post(
            f"{base}/v1/embeddings",
            json={"model": self.model, "input": texts, "input_type": input_type, "output_dimension": self.dim},
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        )
        resp.raise_for_status()
        return [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]


class OpenAIEmbeddings:
    """OpenAI text-embedding-3-large (or any OpenAI-compatible endpoint via EMBEDDING_BASE_URL)."""

    max_batch = 256

    def __init__(self) -> None:
        from openai import OpenAI

        if not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_API_KEY is not set.")
        self.model = settings.resolved_embedding_model
        self.dim = settings.embedding_dim
        self._client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url or None)

    def embed(self, texts, input_type):
        out = []
        for i in range(0, len(texts), self.max_batch):
            resp = self._client.embeddings.create(model=self.model, input=texts[i : i + self.max_batch], dimensions=self.dim)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return _normalise(out, self.dim)


class LocalEmbeddings:
    """Local sentence-transformers model (default BAAI/bge-m3, 1024-d). Needs `pip install sentence-transformers`
    and ~2.5 GB RAM - good for local development / offline ingestion, not for tiny free hosting tiers."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = settings.resolved_embedding_model
        self.dim = settings.embedding_dim
        self._m = SentenceTransformer(self.model)

    def embed(self, texts, input_type):
        vecs = self._m.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
        return _normalise(vecs.tolist(), self.dim)


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return {
        "gemini": GeminiEmbeddings,
        "cohere": CohereEmbeddings,
        "voyage": VoyageEmbeddings,
        "openai": OpenAIEmbeddings,
        "local": LocalEmbeddings,
    }[settings.embedding_provider]()


async def embed_queries(texts: list[str]) -> list[list[float]]:
    """Async wrapper for request-time query embedding (providers are sync HTTP clients)."""
    provider = get_embedding_provider()
    return await asyncio.to_thread(provider.embed, texts, "query")
