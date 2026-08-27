"""Application configuration.

Every value here comes from environment variables (loaded from `backend/.env`).
Nothing secret is ever hardcoded — that is the whole point of this file.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Which provider to call: "claude" or "openai"
    llm_provider: Literal["claude", "openai"] = "claude"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Web search. Tavily is a search API built for LLMs — it returns extracted
    # text and a synthesized answer, so no page-fetching is needed. Leave it
    # empty and search falls back to DuckDuckGo, which needs no key.
    tavily_api_key: str = ""

    # Generation
    system_prompt: str = "You are a friendly, concise assistant."
    max_tokens: int = 2048
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def active_model(self) -> str:
        return self.anthropic_model if self.llm_provider == "claude" else self.openai_model

    @property
    def active_key(self) -> str:
        return self.anthropic_api_key if self.llm_provider == "claude" else self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process."""
    return Settings()
