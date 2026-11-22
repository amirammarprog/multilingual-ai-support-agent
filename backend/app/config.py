"""Application settings, read from environment variables (see `.env.example`).

Nothing secret has a default value: keys stay empty until the operator sets them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True
    demo_mode: bool = Field(
        default=True,
        description="Enables the demo endpoints that sign identity tokens for the fictional customers.",
    )
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]

    # --- Database -------------------------------------------------------------------------------
    # The app connects as a role without BYPASSRLS so PostgreSQL row-level security applies.
    database_url: str = "postgresql+psycopg://support_app:support_app@localhost:5432/support"
    # Migrations and seeding run as the table owner.
    migration_database_url: str = "postgresql+psycopg://support:support@localhost:5432/support"
    db_pool_size: int = 5

    # --- Auth -----------------------------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "support-agent"
    staff_token_ttl_minutes: int = 60 * 8
    widget_session_ttl_minutes: int = 60 * 12

    # --- Rate limits (requests per window) ------------------------------------------------------
    rate_limit_window_seconds: int = 60
    rate_limit_chat_per_session: int = 20
    rate_limit_chat_per_ip: int = 60
    rate_limit_login_per_ip: int = 10
    rate_limit_session_create_per_ip: int = 30
    order_verification_max_failures: int = 5

    # --- LLM providers --------------------------------------------------------------------------
    # Any OpenAI-compatible endpoint works: OpenAI, OpenRouter, Groq, vLLM, Ollama, llama.cpp server.
    llm_primary_base_url: str = "https://api.openai.com/v1"
    llm_primary_api_key: SecretStr = SecretStr("")
    llm_primary_fast_model: str = "gpt-4.1-nano"
    llm_primary_smart_model: str = "gpt-4.1-mini"
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: SecretStr = SecretStr("")
    llm_fallback_fast_model: str = ""
    llm_fallback_smart_model: str = ""
    llm_timeout_seconds: float = 120.0
    llm_temperature: float = 0.1
    # Local models (llama.cpp / Ollama) need the thinking switch turned off for Qwen3-style models.
    llm_disable_thinking: bool = False
    # Optional "reasoning_effort" sent to reasoning models (e.g. "low"); empty = not sent.
    llm_reasoning_effort: str = ""
    # auto: strict JSON schema, switching to JSON mode for models that reject it.
    llm_response_format: Literal["auto", "json_schema", "json_object"] = "auto"
    # Free tiers: client-side request pacing (0 = none) and retries on 429 / 5xx / network errors.
    llm_primary_requests_per_minute: int = 0
    llm_fallback_requests_per_minute: int = 0
    llm_max_retries: int = 4
    llm_retry_base_seconds: float = 2.0
    # A wait longer than this (a daily quota) fails the call instead of blocking.
    llm_max_retry_wait_seconds: float = 90.0
    # Evaluation judge. Empty JUDGE_MODEL = the primary provider's smart model.
    judge_model: str = ""
    judge_base_url: str = ""
    judge_api_key: SecretStr = SecretStr("")
    judge_requests_per_minute: int = 0
    # "auto" uses the complexity router; the other two force a tier (useful to compare in evals).
    router_mode: Literal["auto", "always_fast", "always_smart"] = "auto"
    router_smart_threshold: float = 0.5
    # USD per 1M tokens, used for cost estimates. JSON object: {"model": [input, output]}.
    model_prices: dict[str, tuple[float, float]] = {
        "gpt-4.1-nano": (0.10, 0.40),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1": (2.00, 8.00),
    }

    # --- RAG ------------------------------------------------------------------------------------
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    reranker_provider: Literal["cross_encoder", "none"] = "cross_encoder"
    # Multilingual cross-encoder trained on mMARCO (14 languages incl. Arabic and French), AVX2 int8 build.
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_model_file: str = "onnx/model_quint8_avx2.onnx"
    model_cache_dir: str = "/models"
    chunk_size: int = 900
    chunk_overlap: int = 150
    retrieval_candidates: int = 8
    retrieval_top_k: int = 4
    # Minimum reranker probability for a chunk to count as evidence.
    retrieval_min_score: float = 0.15
    max_upload_mb: int = 10

    # --- Voice ----------------------------------------------------------------------------------
    stt_provider: Literal["local_whisper", "openai", "disabled"] = "local_whisper"
    whisper_model: str = "base"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    tts_provider: Literal["browser", "openai"] = "browser"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    voice_api_key: SecretStr = SecretStr("")
    max_audio_seconds: int = 60

    # --- Observability --------------------------------------------------------------------------
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "http://localhost:3000"

    # --- Agent ----------------------------------------------------------------------------------
    history_turns: int = 6
    max_message_chars: int = 2000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def llm_configured(self) -> bool:
        primary = bool(self.llm_primary_api_key.get_secret_value()) or self._is_local(self.llm_primary_base_url)
        return primary or bool(self.llm_fallback_base_url)

    @staticmethod
    def _is_local(url: str) -> bool:
        return any(h in url for h in ("localhost", "127.0.0.1", "llm:", "ollama:", "host.docker.internal"))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.jwt_secret.get_secret_value():
        if settings.app_env == "production":
            raise RuntimeError("JWT_SECRET must be set in production")
        # Development/test only: a random secret per process, so tokens never survive a restart.
        import secrets

        settings.jwt_secret = SecretStr(secrets.token_urlsafe(48))
    return settings
