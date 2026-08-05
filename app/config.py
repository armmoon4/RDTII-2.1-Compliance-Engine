"""Application configuration — loads from .env / environment variables."""
import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    app_name: str = "RDTII 2.1 Compliance Engine"
    app_version: str = "4.0.0"
    app_env: str = "development"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"
    allowed_origins: str = "http://localhost:8501,http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://rdtii_user:rdtii_pass@localhost:5432/rdtii_db"
    )
    database_url_sync: str = (
        "postgresql://rdtii_user:rdtii_pass@localhost:5432/rdtii_db"
    )

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── LLM ──────────────────────────────────────────────────────────────────
    google_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    deepseek_api_key: str = ""
    tokenrouter_api_key: str = ""
    tokenrouter_base_url: str = "https://api.tokenrouter.com/v1"
    tokenrouter_model: str = "MiniMax-M3"
    minimax_model: str = "MiniMax-M3"
    nvidia_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    llm_provider: str = "auto"  # "auto" | "minimax" | "nvidia" | "gemini" | "openai" | "grok" | "deepseek" | "tokenrouter" | "ollama"

    # ── Search ────────────────────────────────────────────────────────────────
    tavily_api_key: str = ""
    max_search_results_per_query: int = 10
    max_queries_per_indicator: int = 7
    download_timeout_seconds: int = 30
    max_document_size_mb: int = 50
    search_rate_limit_seconds: float = 1.0
    llm_enhanced_queries: bool = True  # Use LLM to generate smarter search queries per indicator

    # ── ChromaDB & Embeddings ────────────────────────────────────────────────
    chroma_db_path: str = str(Path(__file__).resolve().parent.parent / "chroma_db")
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    max_total_chunks: int = 1500               # cap total chunks to limit embedding time (~1500 = ~10 min)

    # ── Score inversion ───────────────────────────────────────────────────────
    # Indicators where absence of framework = HIGHER score (inverted logic).
    # Per RDTII spec: 7.1, 7.2, 8.1, 8.2, 9.1, 12.9
    inverted_indicators: List[str] = [
        "7.1", "7.2", "8.1", "8.2", "9.1", "12.9",
    ]

    # ── Supported countries ───────────────────────────────────────────────────
    supported_countries: List[str] = ["Malaysia", "Singapore", "Australia"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
