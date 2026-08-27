"""Request / response shapes for the chat API.

FastAPI validates incoming JSON against these models and documents them
automatically at http://127.0.0.1:8000/docs.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .catalog import EFFORT_LEVELS
from .tools import BACKENDS as SEARCH_BACKENDS

Provider = Literal["claude", "openai"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
SearchBackend = Literal["auto", "tavily", "duckduckgo", "compare"]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatConfig(BaseModel):
    """Overrides sent by the configuration panel.

    Every field is optional — anything left out falls back to the value in
    backend/.env, so the API still works from curl with no config at all.
    """

    provider: Provider | None = None
    model: str | None = Field(default=None, max_length=100)
    # Let the model look things up when the answer needs current facts.
    web_search: bool = False
    # Which search backend runs. "compare" runs both and times them.
    search_backend: SearchBackend = "auto"
    system_prompt: str | None = Field(default=None, max_length=8000)
    max_tokens: int | None = Field(default=None, ge=64, le=32000)
    effort: Effort | None = None


class ClientContext(BaseModel):
    """Facts the browser knows and the server does not.

    Injected into the system prompt rather than exposed as a tool: they are
    always relevant and free to compute, so making the model ask for them
    would waste a round-trip on every single message.
    """

    # IANA zone, e.g. "Asia/Kolkata". The browser reports this with no
    # permission prompt, unlike real geolocation.
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=32)


class ChatRequest(BaseModel):
    """The frontend sends the whole conversation on every turn.

    LLM APIs are stateless — they do not remember previous calls, so the full
    history is what gives the bot its memory.
    """

    messages: list[Message] = Field(min_length=1, max_length=200)
    config: ChatConfig = Field(default_factory=ChatConfig)
    context: ClientContext = Field(default_factory=ClientContext)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    # The model's summarized reasoning, when the model produced any and the
    # request asked for it. Empty string means "no reasoning to show".
    thinking: str = ""


class ModelOption(BaseModel):
    id: str
    label: str
    hint: str = ""
    # True/False when the provider's models endpoint answered, None if unknown.
    available: bool | None = None
    # Reasoning / search parameters are per-model, not per-provider — see
    # catalog.py.
    supports_effort: bool = False
    supports_thinking: bool = False
    supports_search: bool = False


class ProviderOption(BaseModel):
    id: str
    label: str
    vendor: str
    supports_effort: bool
    api_key_configured: bool
    models: list[ModelOption]


class ConfigResponse(BaseModel):
    """Everything the configuration panel needs to build itself."""

    providers: list[ProviderOption]
    effort_levels: list[str] = EFFORT_LEVELS
    search_backends: list[str] = SEARCH_BACKENDS
    # False when no TAVILY_API_KEY is set, so the panel can say why.
    tavily_configured: bool = False
    defaults: ChatConfig
    max_tokens_limit: int = 32000
