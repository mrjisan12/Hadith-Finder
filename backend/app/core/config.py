"""Application settings, loaded from environment variables / the project-root `.env`.

Secrets are only ever read here and never logged (see `Settings.safe_dict`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Project-root .env first, then backend/.env (later files win).
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    enable_debug: bool = True  # exposes retrieval debug info + /debug endpoints
    data_dir: Path = PROJECT_ROOT / "data"

    # --------------------------------------------------------------- database
    database_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # ---------------------------------------------------------------- storage
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str = ""
    supabase_anon_key: str = ""  # not used by the backend; documented for completeness
    supabase_service_role_key: str = ""
    storage_bucket: str = "books"
    storage_public: bool = True
    storage_signed_url_ttl: int = 3600

    # -------------------------------------------------------------------- LLM
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_api_key: str = ""
    llm_base_url: str = ""  # for OpenAI-compatible providers (Gemini, Groq, OpenRouter, ...)
    llm_model: str = "claude-opus-5"
    llm_fast_model: str = ""  # query understanding + LLM reranking; defaults to llm_model
    llm_answer_effort: str = "medium"  # Anthropic effort for answer synthesis
    llm_fast_effort: str = "low"  # Anthropic effort for helper calls
    llm_refusal_fallback: bool = True  # Anthropic server-side refusal fallbacks
    llm_timeout_seconds: float = 90.0
    llm_max_answer_tokens: int = 4000

    # ------------------------------------------------------------- embeddings
    embedding_provider: Literal["gemini", "openai", "cohere", "voyage", "local"] = "gemini"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""  # provider default when empty
    embedding_dim: int = 1024
    embedding_batch_size: int = 64

    # -------------------------------------------------------------- reranking
    reranker_provider: Literal["llm", "cohere", "jina", "none"] = "llm"
    reranker_api_key: str = ""
    reranker_model: str = ""
    # normalised 0..1; below this a passage is "not relevant". Empty = reranker default
    # (llm 0.5, cohere 0.15, jina 0.2, none 0).
    rerank_min_score: float | None = None

    # -------------------------------------------------------------- retrieval
    retrieval_vector_k: int = 20
    retrieval_keyword_k: int = 20
    retrieval_rerank_candidates: int = 30
    retrieval_top_k: int = 5
    vector_search_mode: Literal["exact", "hnsw"] = "exact"
    enable_query_understanding: bool = True

    # -------------------------------------------------------------------- OCR
    ocr_provider: Literal["google_vision", "tesseract"] = "google_vision"
    google_vision_api_key: str = ""
    tesseract_cmd: str = ""
    tesseract_langs: str = "ben+ara+urd"

    # ------------------------------------------------------ security / infra
    cors_origins: str = "http://localhost:3000"
    rate_limit_chat: str = "20/minute"
    rate_limit_default: str = "120/minute"
    redis_url: str = ""
    max_query_chars: int = 1000

    # -------------------------------------------------------------- validators
    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        v = v.strip()
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("rerank_min_score", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if v in ("", None) else v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fast_model(self) -> str:
        return self.llm_fast_model or self.llm_model

    @property
    def resolved_embedding_model(self) -> str:
        if self.embedding_model:
            return self.embedding_model
        return {
            "gemini": "gemini-embedding-001",
            "openai": "text-embedding-3-large",
            "cohere": "embed-multilingual-v3.0",
            "voyage": "voyage-3.5",
            "local": "BAAI/bge-m3",
        }[self.embedding_provider]

    def safe_dict(self) -> dict:
        """Settings with every secret redacted - safe to log."""
        secret_markers = ("key", "password", "secret", "token")
        out = {}
        for k, v in self.model_dump().items():
            if any(m in k for m in secret_markers):
                out[k] = "***set***" if v else ""
            elif k == "database_url" and v:
                out[k] = v.split("@")[-1]  # host/db only
            else:
                out[k] = str(v) if isinstance(v, Path) else v
        return out


class _SettingsProxy:
    """Allows `settings.x` everywhere while still supporting cache resets in tests."""

    def __getattr__(self, item):
        return getattr(get_settings(), item)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = _SettingsProxy()  # type: ignore[assignment]
