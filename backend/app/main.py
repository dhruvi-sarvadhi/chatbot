"""FastAPI app exposing the chatbot API to the React frontend.

Run it with:  uvicorn app.main:app --reload   (from the backend/ folder)
Interactive docs:  http://127.0.0.1:8000/docs
"""

import json
import logging
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .catalog import PROVIDERS
from .config import get_settings
from .providers import GenerationConfig, get_provider
from .schemas import (
    ChatConfig,
    ChatRequest,
    ClientContext,
    ChatResponse,
    ConfigResponse,
    ModelOption,
    ProviderOption,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chatbot")

settings = get_settings()

app = FastAPI(
    title="Chatbot API",
    description="Thin wrapper around Claude / OpenAI for the React chat UI.",
    version="2.0.0",
)

# The browser calls this API from a different port (5173), so it needs CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KEY_ENV_NAME = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@lru_cache
def _live_model_ids(provider: str) -> frozenset[str]:
    """Ask the provider which models this key can use.

    Cached for the life of the process — it is one extra HTTP round-trip and
    the answer barely changes. Restart the server to refresh it.
    """
    try:
        return frozenset(get_provider(provider).list_models())
    except Exception:  # noqa: BLE001 — never let this break the panel
        log.warning("could not list models for %s", provider)
        return frozenset()


def _key_for(provider: str) -> str:
    key = settings.anthropic_api_key if provider == "claude" else settings.openai_api_key
    # The shipped .env.example uses obvious placeholders — treat those as unset.
    return "" if "xxxxxxxx" in key else key


def _now_block(ctx: ClientContext) -> str:
    """The always-relevant facts, as plain text for the system prompt.

    Injected rather than offered as a tool: a tool call to ask the clock the
    time would cost a full extra round-trip on every message that mentions
    "today". Cheap and always-relevant belongs in the prompt.
    """
    tz = None
    if ctx.timezone:
        try:
            tz = ZoneInfo(ctx.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            # A bogus zone from the client must not take the whole chat down.
            log.warning("unknown timezone from client: %r", ctx.timezone)

    now = datetime.now(tz)
    lines = [f"The current date and time is {now:%A, %d %B %Y, %H:%M} ({now:%Z})."]
    if tz is not None:
        lines.append(f"The user's timezone is {ctx.timezone}.")
    lines.append("Use this for anything relative — today, tomorrow, this week.")
    return "\n".join(lines)


def _resolve(cfg: ChatConfig, ctx: ClientContext) -> tuple[str, GenerationConfig]:
    """Merge the panel's overrides over the .env defaults."""
    provider = cfg.provider or settings.llm_provider

    if not _key_for(provider):
        raise HTTPException(
            status_code=400,
            detail=f"No API key for {provider} — set {KEY_ENV_NAME[provider]} in backend/.env",
        )

    default_model = (
        settings.anthropic_model if provider == "claude" else settings.openai_model
    )
    system = cfg.system_prompt or settings.system_prompt
    return provider, GenerationConfig(
        model=cfg.model or default_model,
        system=f"{system}\n\n{_now_block(ctx)}",
        max_tokens=cfg.max_tokens or settings.max_tokens,
        effort=cfg.effort or settings.effort,
        web_search=cfg.web_search,
    )


@app.get("/api/config", response_model=ConfigResponse)
def config() -> ConfigResponse:
    """Everything the left-hand configuration panel renders itself from.

    Model ids are cross-checked against each provider's live models endpoint,
    so the panel can grey out anything your key cannot reach.
    """
    providers = []
    for pid, meta in PROVIDERS.items():
        has_key = bool(_key_for(pid))

        live_ids = _live_model_ids(pid) if has_key else frozenset()

        providers.append(
            ProviderOption(
                id=pid,
                label=meta["label"],
                vendor=meta["vendor"],
                supports_effort=meta["supports_effort"],
                api_key_configured=has_key,
                models=[
                    ModelOption(
                        **m,
                        available=(m["id"] in live_ids) if live_ids else None,
                    )
                    for m in meta["models"]
                ],
            )
        )

    return ConfigResponse(
        providers=providers,
        defaults=ChatConfig(
            provider=settings.llm_provider,
            model=settings.active_model,
            system_prompt=settings.system_prompt,
            max_tokens=settings.max_tokens,
            effort=settings.effort,
        ),
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Simple version: wait for the whole answer, then return it."""
    provider_name, gen = _resolve(request.config, request.context)
    provider = get_provider(provider_name)
    history = [m.model_dump() for m in request.messages]

    try:
        result = provider.chat(history, gen)
    except Exception as exc:  # noqa: BLE001 — surface a readable error to the UI
        log.exception("chat failed")
        raise HTTPException(status_code=502, detail=_friendly(exc, provider_name)) from exc

    return ChatResponse(
        reply=result.text,
        thinking=result.thinking,
        provider=provider_name,
        model=gen.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Streaming version: push each piece to the browser as it is generated.

    The format is SSE (Server-Sent Events): one `data: {...}` line per event.
    First event carries the resolved provider/model, the last carries usage.
    In between: `trace` events (one per step of the agent loop), `status`
    events (web search activity), `thinking` events (the model reasoning) and
    `delta` events (the answer). Separate keys so the UI can render each in
    its own place.
    """
    provider_name, gen = _resolve(request.config, request.context)
    provider = get_provider(provider_name)
    history = [m.model_dump() for m in request.messages]

    def event_source():
        yield _sse({"meta": {"provider": provider_name, "model": gen.model}})
        try:
            for chunk in provider.stream(history, gen):
                if chunk.done:
                    yield _sse(
                        {
                            "usage": {
                                "input_tokens": chunk.input_tokens,
                                "output_tokens": chunk.output_tokens,
                            }
                        }
                    )
                elif chunk.trace:
                    yield _sse({"trace": chunk.trace})
                elif chunk.status:
                    yield _sse({"status": chunk.status})
                elif chunk.thinking:
                    yield _sse({"thinking": chunk.thinking})
                elif chunk.text:
                    yield _sse({"delta": chunk.text})
        except Exception as exc:  # noqa: BLE001
            log.exception("stream failed")
            yield _sse({"error": _friendly(exc, provider_name)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _friendly(exc: Exception, provider: str) -> str:
    text = str(exc)
    low = text.lower()
    if "authentication" in low or "api key" in low or "401" in text:
        return f"API key rejected — check {KEY_ENV_NAME[provider]} in backend/.env"
    if "rate" in low and "limit" in low:
        return "Rate limited by the provider. Wait a moment and try again."
    if "model" in low and ("not found" in low or "does not exist" in low):
        return "That model is not available on your account — pick another one."
    return text[:400]
