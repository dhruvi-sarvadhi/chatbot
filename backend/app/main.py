"""FastAPI app exposing the chatbot API to the React frontend.

Run it with:  uvicorn app.main:app --reload   (from the backend/ folder)
Interactive docs:  http://127.0.0.1:8000/docs
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DbSession

from . import store
from .catalog import PROVIDERS
from .config import get_settings
from .db import get_db, init_db, session_scope
from .pricing import estimate_cost
from .providers import GenerationConfig, get_provider
from .providers.base import TurnMetrics
from .schemas import (
    ChatConfig,
    ChatRequest,
    ClientContext,
    ChatResponse,
    ConfigResponse,
    DeletedResponse,
    LikeUpdate,
    MessageOut,
    ModelOption,
    ProviderOption,
    RunOut,
    SessionCreate,
    SessionDetail,
    SessionSummary,
    SessionUpdate,
    StatsResponse,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("chatbot")

settings = get_settings()

# Set once at startup: False means Postgres could not be reached, so the API
# answers normally but saves nothing rather than failing every request.
DB_READY = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the database and its tables before the first request lands."""
    global DB_READY
    DB_READY = init_db() if settings.persistence_enabled else False
    if settings.persistence_enabled and not DB_READY:
        log.warning("running without persistence — check DATABASE_URL in backend/.env")
    yield


app = FastAPI(
    title="Chatbot API",
    description="Claude / OpenAI chat with conversations stored in PostgreSQL.",
    version="3.0.0",
    lifespan=lifespan,
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
        search_backend=cfg.search_backend,
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
        tavily_configured=bool(settings.tavily_api_key),
        defaults=ChatConfig(
            provider=settings.llm_provider,
            model=settings.active_model,
            system_prompt=settings.system_prompt,
            max_tokens=settings.max_tokens,
            effort=settings.effort,
        ),
    )


# ── persistence helpers ────────────────────────────────────────────────────
#
# Saving must never be able to break answering. Every helper below swallows
# database errors and returns None, so a chat continues to work with Postgres
# down — it just stops being remembered.


def _persist_start(request: ChatRequest, provider_name: str, gen: GenerationConfig):
    """Open (or reopen) the conversation and store the incoming history.

    Returns the session id, or None if nothing was saved. Runs in its own
    transaction and commits before generation begins, so the user's question
    is on disk even if the model call then fails.
    """
    if not DB_READY:
        return None

    cfg = request.config
    try:
        with session_scope() as db:
            session = store.get_session(db, request.session_id)
            if session is None:
                session = store.create_session(db)

            store.update_session(
                db,
                session,
                provider=provider_name,
                model=gen.model,
                # The effective prompt, not just the panel's override — a
                # transcript should record what the model was actually told.
                # (Without the injected date block, which is not a setting.)
                system_prompt=cfg.system_prompt or settings.system_prompt,
                effort=gen.effort,
                max_tokens=gen.max_tokens,
                search_backend=gen.search_backend,
                timezone=request.context.timezone,
                locale=request.context.locale,
            )
            # Not via update_session: it skips None, and False is a real value.
            session.web_search = bool(cfg.web_search)

            store.sync_history(db, session, [m.model_dump() for m in request.messages])
            return session.id
    except SQLAlchemyError:
        log.exception("could not save the incoming turn")
        return None


def _persist_answer(session_id, *, content, metrics=None, **fields):
    """Store a finished answer and what it cost. Returns the message id."""
    if not DB_READY or session_id is None:
        return None
    try:
        with session_scope() as db:
            session = store.get_session(db, session_id)
            if session is None:  # deleted from another tab mid-answer
                return None
            message = store.add_message(
                db, session, role="assistant", content=content, **fields
            )
            if metrics is not None:
                store.add_run(db, session, metrics, message=message)
            return message.id
    except SQLAlchemyError:
        log.exception("could not save the answer")
        return None


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Simple version: wait for the whole answer, then return it."""
    provider_name, gen = _resolve(request.config, request.context)
    provider = get_provider(provider_name)
    history = [m.model_dump() for m in request.messages]

    session_id = _persist_start(request, provider_name, gen)
    started = time.perf_counter()

    try:
        result = provider.chat(history, gen)
    except Exception as exc:  # noqa: BLE001 — surface a readable error to the UI
        log.exception("chat failed")
        # Record the failure against the conversation: a transcript that
        # silently skips the turn that broke is the one you cannot debug.
        _persist_answer(
            session_id,
            content="",
            provider=provider_name,
            model=gen.model,
            incomplete=True,
            error=_friendly(exc, provider_name),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise HTTPException(status_code=502, detail=_friendly(exc, provider_name)) from exc

    # `chat()` returns tokens but no TurnMetrics — only the streaming path
    # instruments the loop. Build the equivalent here so a non-streamed turn
    # still shows up in the analytics instead of silently costing nothing.
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    metrics = TurnMetrics(
        provider=provider_name,
        model=gen.model,
        effort=gen.effort,
        input_tokens=result.input_tokens or 0,
        output_tokens=result.output_tokens or 0,
        model_requests=1,
        total_ms=elapsed_ms,
        model_ms=elapsed_ms,
        search_backend=gen.search_backend if gen.web_search else "",
    )

    message_id = _persist_answer(
        session_id,
        content=result.text,
        thinking=result.thinking,
        provider=provider_name,
        model=gen.model,
        metrics=metrics,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=elapsed_ms,
    )

    return ChatResponse(
        reply=result.text,
        thinking=result.thinking,
        provider=provider_name,
        model=gen.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        session_id=str(session_id) if session_id else None,
        message_id=str(message_id) if message_id else None,
    )


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Streaming version: push each piece to the browser as it is generated.

    The format is SSE (Server-Sent Events): one `data: {...}` line per event.
    First event carries the resolved provider/model and the session id, the
    last carries usage. In between: `trace` events (one per step of the agent
    loop), `status` events (web search activity), `thinking` events (the model
    reasoning) and `delta` events (the answer). Separate keys so the UI can
    render each in its own place.

    The whole answer is accumulated as it streams and written to Postgres once
    the stream ends — including when it ends badly, in which case the row is
    flagged `incomplete` and keeps whatever text had arrived.
    """
    provider_name, gen = _resolve(request.config, request.context)
    provider = get_provider(provider_name)
    history = [m.model_dump() for m in request.messages]

    session_id = _persist_start(request, provider_name, gen)

    def event_source():
        yield _sse(
            {
                "meta": {
                    "provider": provider_name,
                    "model": gen.model,
                    "session_id": str(session_id) if session_id else None,
                }
            }
        )

        # Rebuilt here rather than read back from the UI, so what gets stored
        # is exactly what the model produced.
        answer: list[str] = []
        thinking: list[str] = []
        trace: list[dict] = []
        search = None
        metrics = None
        usage = {}
        error = None
        started = time.perf_counter()

        try:
            for chunk in provider.stream(history, gen):
                if chunk.done:
                    metrics = chunk.metrics
                    usage = {
                        "input_tokens": chunk.input_tokens,
                        "output_tokens": chunk.output_tokens,
                    }
                    yield _sse({"usage": usage, "metrics": _metrics_payload(chunk.metrics)})
                elif chunk.trace:
                    trace.append(chunk.trace)
                    yield _sse({"trace": chunk.trace})
                elif chunk.status:
                    search = chunk.status
                    yield _sse({"status": chunk.status})
                elif chunk.thinking:
                    thinking.append(chunk.thinking)
                    yield _sse({"thinking": chunk.thinking})
                elif chunk.text:
                    answer.append(chunk.text)
                    yield _sse({"delta": chunk.text})
        except Exception as exc:  # noqa: BLE001
            log.exception("stream failed")
            error = _friendly(exc, provider_name)
            yield _sse({"error": error})

        message_id = _persist_answer(
            session_id,
            content="".join(answer),
            thinking="".join(thinking),
            provider=provider_name,
            model=gen.model,
            search=search,
            trace=trace or None,
            metrics=metrics,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            incomplete=error is not None,
            error=error,
        )
        # Sent last: the id only exists once the row is written, and the UI
        # needs it to like the message or reopen the conversation.
        if message_id:
            yield _sse({"saved": {"message_id": str(message_id)}})

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _metrics_payload(metrics) -> dict | None:
    """Per-turn analytics for the UI, with the cost worked out server-side."""
    if metrics is None:
        return None
    data = asdict(metrics)
    # None rather than 0 when the model is not in the pricing table, so the UI
    # can show "—" instead of implying the turn was free.
    data["cost_usd"] = estimate_cost(
        metrics.model, metrics.input_tokens, metrics.output_tokens
    )
    return data


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


# ── stored conversations ───────────────────────────────────────────────────


def _require_db() -> None:
    """Guard for the endpoints that only make sense with a database."""
    if not DB_READY:
        raise HTTPException(
            status_code=503,
            detail="History is unavailable — the database is not reachable. "
            "Check DATABASE_URL in backend/.env and that PostgreSQL is running.",
        )


def _summary(row: dict) -> SessionSummary:
    """Flatten a store row (session + aggregates) into the wire shape."""
    session = row["session"]
    return SessionSummary(
        id=session.id,
        title=session.title,
        provider=session.provider,
        model=session.model,
        archived=session.archived,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
        message_count=row["message_count"],
        run_count=row["run_count"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
    )


def _detail(session, totals: dict) -> SessionDetail:
    """A conversation with its transcript, ready to be rendered again.

    Each message carries its own run, so the UI gets one object per bubble and
    does not have to join tokens back onto messages in the browser.
    """
    return SessionDetail(
        id=session.id,
        title=session.title,
        provider=session.provider,
        model=session.model,
        archived=session.archived,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
        message_count=sum(1 for m in session.messages if not m.incomplete),
        run_count=totals["run_count"],
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
        cost_usd=totals["cost_usd"],
        system_prompt=session.system_prompt,
        effort=session.effort,
        max_tokens=session.max_tokens,
        web_search=session.web_search,
        search_backend=session.search_backend,
        timezone=session.timezone,
        locale=session.locale,
        messages=[
            MessageOut(
                **{
                    k: getattr(m, k)
                    for k in (
                        "id", "seq", "role", "content", "thinking", "provider",
                        "model", "search", "trace", "liked", "input_tokens",
                        "output_tokens", "latency_ms", "thinking_ms",
                        "incomplete", "error", "created_at",
                    )
                },
                metrics=RunOut.model_validate(m.run) if m.run else None,
            )
            for m in session.messages
        ],
        runs=[RunOut.model_validate(r) for r in session.runs],
    )


@app.get("/api/sessions", response_model=list[SessionSummary])
def list_sessions(
    db: DbSession = Depends(get_db),
    include_archived: bool = Query(False, description="Also return archived chats"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[SessionSummary]:
    """The sidebar. Newest activity first, with per-conversation totals."""
    _require_db()
    return [_summary(row) for row in store.list_sessions(
        db, include_archived=include_archived, limit=limit, offset=offset
    )]


@app.post("/api/sessions", response_model=SessionDetail, status_code=201)
def create_session(
    body: SessionCreate | None = None, db: DbSession = Depends(get_db)
) -> SessionDetail:
    """Start an empty conversation.

    Optional — posting a chat with no `session_id` opens one too. This exists
    so the UI can create the row the moment you click "New chat", before there
    is anything to say.
    """
    _require_db()
    body = body or SessionCreate()
    cfg = body.config or ChatConfig()
    ctx = body.context

    session = store.create_session(
        db,
        title=body.title or "New chat",
        provider=cfg.provider or settings.llm_provider,
        model=cfg.model or settings.active_model,
        system_prompt=cfg.system_prompt,
        effort=cfg.effort,
        max_tokens=cfg.max_tokens,
        web_search=bool(cfg.web_search),
        search_backend=cfg.search_backend,
        timezone=ctx.timezone if ctx else None,
        locale=ctx.locale if ctx else None,
    )
    return _detail(session, store.session_totals(db, session.id))


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: DbSession = Depends(get_db)) -> SessionDetail:
    """One conversation with its full transcript, reasoning and metrics."""
    _require_db()
    session = store.get_session_full(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    return _detail(session, store.session_totals(db, session.id))


@app.patch("/api/sessions/{session_id}", response_model=SessionSummary)
def patch_session(
    session_id: str, body: SessionUpdate, db: DbSession = Depends(get_db)
) -> SessionSummary:
    """Rename or archive a conversation."""
    _require_db()
    session = store.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such conversation")

    if body.title is not None:
        session.title = body.title.strip() or session.title
    if body.archived is not None:
        session.archived = body.archived
    db.flush()

    return _summary(
        {
            "session": session,
            "message_count": store.message_count(db, session.id),
            **store.session_totals(db, session.id),
        }
    )


@app.delete("/api/sessions/{session_id}", response_model=DeletedResponse)
def remove_session(session_id: str, db: DbSession = Depends(get_db)) -> DeletedResponse:
    """Delete a conversation and everything under it."""
    _require_db()
    session = store.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    store.delete_session(db, session)
    return DeletedResponse(deleted=1)


@app.delete("/api/sessions", response_model=DeletedResponse)
def remove_all_sessions(
    db: DbSession = Depends(get_db),
    archived_only: bool = Query(False, description="Only clear archived chats"),
) -> DeletedResponse:
    """Wipe the history. Irreversible, so the UI asks first."""
    _require_db()
    return DeletedResponse(deleted=store.delete_all_sessions(db, archived_only=archived_only))


@app.get("/api/sessions/{session_id}/runs", response_model=list[RunOut])
def session_runs(session_id: str, db: DbSession = Depends(get_db)) -> list[RunOut]:
    """Every turn's cost for one conversation, oldest first."""
    _require_db()
    if store.get_session(db, session_id) is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    return [RunOut.model_validate(r) for r in store.session_runs(db, session_id)]


@app.patch("/api/messages/{message_id}/like", response_model=MessageOut)
def like_message(
    message_id: str, body: LikeUpdate, db: DbSession = Depends(get_db)
) -> MessageOut:
    """Persist the thumbs-up, so it survives a reload."""
    _require_db()
    message = store.set_liked(db, message_id, body.liked)
    if message is None:
        raise HTTPException(status_code=404, detail="No such message")
    return MessageOut.model_validate(message)


@app.get("/api/stats", response_model=StatsResponse)
def usage_stats(db: DbSession = Depends(get_db)) -> StatsResponse:
    """Totals across every stored conversation, plus a per-model breakdown."""
    _require_db()
    return StatsResponse(**store.stats(db))


@app.get("/api/health")
def health() -> dict:
    """Is the API up, and is it currently remembering anything."""
    return {
        "status": "ok",
        "database": "connected" if DB_READY else "unavailable",
        "database_name": settings.db_name if DB_READY else None,
        "persistence_enabled": settings.persistence_enabled,
    }
