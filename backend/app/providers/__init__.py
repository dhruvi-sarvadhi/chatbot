"""Provider factory — builds one client per provider and reuses it."""

from functools import lru_cache

from ..config import get_settings
from .base import ChatProvider, ChatResult, GenerationConfig, StreamChunk

__all__ = ["ChatProvider", "ChatResult", "GenerationConfig", "StreamChunk", "get_provider"]


@lru_cache
def get_provider(name: str) -> ChatProvider:
    """Cached per provider name, so we don't open a new HTTP client per request.

    Model / effort / system prompt are *not* baked in here — they arrive with
    each request, which is what lets the config panel change them live.
    """
    settings = get_settings()

    if name == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider(
            api_key=settings.anthropic_api_key,
            default_model=settings.anthropic_model,
        )

    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            default_model=settings.openai_model,
        )

    raise ValueError(f"Unknown provider: {name}")
