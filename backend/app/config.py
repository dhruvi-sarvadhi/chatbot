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

    # Which provider to call: "claude", "openai" or "kie"
    llm_provider: Literal["claude", "openai", "kie"] = "claude"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ── kie.ai (GPT-6 Astra) ────────────────────────────────────────────
    # A gateway that re-publishes OpenAI's Responses API, giving access to
    # the Codex-tier models — GPT-6 Astra and the gpt-5-6 family — on a flat
    # kie.ai key instead of an OpenAI account. Leave the key empty and the
    # provider is simply greyed out in the panel.
    # Key: https://kie.ai → API keys.
    kie_api_key: str = ""
    kie_model: str = "gpt-6-astra"
    # Overridable so a self-hosted or regional gateway can be pointed at
    # without a code change. `/codex/v1`, not `/v1` — see kie_provider.py.
    kie_base_url: str = "https://api.kie.ai/codex/v1"

    # Web search. Tavily is a search API built for LLMs — it returns extracted
    # text and a synthesized answer, so no page-fetching is needed. Leave it
    # empty and search falls back to DuckDuckGo, which needs no key.
    tavily_api_key: str = ""

    # ── Clarix Projects API ─────────────────────────────────────────────
    # Lets the model read and write real projects and tasks. Leave the key
    # empty and the tool is simply not offered to the model — nothing breaks.
    #
    # The URL is the GATEWAY, which is the only public entry point. Note there
    # is no `/projects-api` prefix: the app answers on bare paths (`/projects`,
    # `/tasks`). See clarix_client.py for why that matters.
    clarix_api_url: str = "http://localhost:5100"
    # A long-lived key (`clx_live_<workspace>_…`) issued from
    # Clarix → Settings → API access. It acts as the person who created it, so
    # it can do exactly what they can do and no more.
    clarix_api_key: str = ""
    # Clarix encrypts every response body when ENABLE_PAYLOAD_ENCRYPTION=true
    # (its local and production default), so a client needs this as a SECOND
    # shared secret just to read replies. Copy ENCRYPTION_KEY verbatim from the
    # Clarix backend's .env.local — only the first 32 chars are used, but paste
    # the whole thing so it stays comparable with the server's value.
    clarix_encryption_key: str = ""

    # Where generated images are written. Relative paths are resolved against
    # the backend/ folder. Served read-only at /media — see media.py.
    media_dir: str = "media"

    # Generation
    system_prompt: str = "You are a friendly, concise assistant."
    max_tokens: int = 2048
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"

    # ── Database ────────────────────────────────────────────────────────
    # Where conversations are stored. SQLAlchemy URL; the app creates the
    # database and its tables on first start if they are not there yet.
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/chatbot"
    # Log every statement — noisy, but the fastest way to see what the ORM
    # actually sent when a query behaves oddly.
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Turn off to run with no database at all: the chat still answers, it
    # just remembers nothing.
    persistence_enabled: bool = True

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_name(self) -> str:
        return self.database_url.rsplit("/", 1)[-1].split("?")[0]

    def model_for(self, provider: str) -> str:
        """The .env default model for one provider."""
        return {
            "claude": self.anthropic_model,
            "openai": self.openai_model,
            "kie": self.kie_model,
        }.get(provider, "")

    def key_for(self, provider: str) -> str:
        """The .env key for one provider ("" when it is not configured)."""
        return {
            "claude": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "kie": self.kie_api_key,
        }.get(provider, "")

    @property
    def active_model(self) -> str:
        return self.model_for(self.llm_provider)

    @property
    def active_key(self) -> str:
        return self.key_for(self.llm_provider)


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process."""
    return Settings()
