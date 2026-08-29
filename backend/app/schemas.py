"""Request / response shapes for the chat API.

FastAPI validates incoming JSON against these models and documents them
automatically at http://127.0.0.1:8000/docs.
"""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from .catalog import EFFORT_LEVELS
from .tools import BACKENDS as SEARCH_BACKENDS

Provider = Literal["claude", "openai"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
SearchBackend = Literal["auto", "tavily", "duckduckgo", "compare"]


# base64 inflates a file by about a third, so this is roughly a 4 MB upload.
MAX_ATTACHMENT_CHARS = 6_000_000


class Attachment(BaseModel):
    """A file the user attached to one message.

    Three kinds, because they reach the model three different ways:
      image     — sent as an image block; the model looks at it
      document  — sent as a PDF; the provider extracts the pages
      text      — already decoded in the browser and pasted in as text,
                  which is cheaper and works everywhere
    """

    kind: Literal["image", "document", "text"]
    name: str = Field(max_length=200)
    media_type: str = Field(max_length=100)
    # base64 for image/document; the plain contents for text.
    data: str = Field(max_length=MAX_ATTACHMENT_CHARS)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    # May be empty when the message is only an attachment — "what is this?"
    # is often carried entirely by the picture.
    content: str = Field(default="", max_length=100_000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.content.strip() and not self.attachments:
            raise ValueError("a message needs text, an attachment, or both")
        return self


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
    # Which stored conversation this turn belongs to. Omit it and the server
    # opens a new one and returns the id, so a client that knows nothing about
    # sessions still gets its history saved.
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    # Where this turn was stored. None when persistence is off or the
    # database is unreachable — the answer is still returned either way.
    session_id: str | None = None
    message_id: str | None = None
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


# ── Persistence: sessions, stored messages and stored runs ─────────────────


class SessionCreate(BaseModel):
    """Optional body for POST /api/sessions — everything has a default."""

    title: str | None = Field(default=None, max_length=200)
    config: ChatConfig | None = None
    context: ClientContext | None = None


class SessionUpdate(BaseModel):
    """PATCH body. Only the fields present are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


class RunOut(BaseModel):
    """One turn's cost, as stored. Mirrors the live `metrics` SSE payload so
    a reloaded conversation renders through exactly the same UI code."""

    id: UUID4
    provider: str = ""
    model: str = ""
    effort: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    model_requests: int = 0
    tool_calls: int = 0
    total_ms: int = 0
    model_ms: int = 0
    tool_ms: int = 0
    search_backend: str = ""
    cost_usd: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    """A stored transcript entry."""

    id: UUID4
    seq: int
    role: str
    content: str = ""
    thinking: str = ""
    provider: str | None = None
    model: str | None = None
    search: str | None = None
    trace: list | None = None
    liked: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    thinking_ms: int | None = None
    incomplete: bool = False
    error: str | None = None
    created_at: datetime
    metrics: RunOut | None = None

    model_config = ConfigDict(from_attributes=True)


class SessionSummary(BaseModel):
    """A sidebar row: the conversation plus its totals, no message bodies."""

    id: UUID4
    title: str
    provider: str | None = None
    model: str | None = None
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0
    run_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None

    model_config = ConfigDict(from_attributes=True)


class SessionDetail(SessionSummary):
    """A conversation with its full transcript, for reopening it."""

    system_prompt: str | None = None
    effort: str | None = None
    max_tokens: int | None = None
    web_search: bool = False
    search_backend: str | None = None
    timezone: str | None = None
    locale: str | None = None
    messages: list[MessageOut] = []
    runs: list[RunOut] = []


class ModelUsage(BaseModel):
    model: str
    provider: str
    runs: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    avg_ms: int = 0

    model_config = ConfigDict(protected_namespaces=())


class StatsResponse(BaseModel):
    """Everything-so-far analytics across every stored conversation."""

    sessions: int = 0
    messages: int = 0
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    tool_calls: int = 0
    cost_usd: float | None = None
    avg_ms: int = 0
    by_model: list[ModelUsage] = []


class LikeUpdate(BaseModel):
    liked: bool


class DeletedResponse(BaseModel):
    deleted: int
