"""Claude (Anthropic) provider — calls the Messages API with the official SDK."""

import time
from collections.abc import Iterator

import anthropic

from ..catalog import model_caps
from .base import ChatProvider, ChatResult, GenerationConfig, StreamChunk, TurnMetrics

# Server-side refusal fallbacks: if a safety classifier declines the request,
# Anthropic re-routes it to a suitable fallback model instead of returning an
# unusable answer. Delete these two constants to turn it off.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODE = "default"

# Anthropic runs this one on their own servers — we declare it and results come
# back as content blocks in the same response. There is no HTTP call to write
# and no loop to run, unlike a tool we would implement ourselves.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


class ClaudeProvider(ChatProvider):
    name = "claude"

    def __init__(self, api_key: str, default_model: str) -> None:
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is missing — set it in backend/.env")
        # The SDK reads ANTHROPIC_API_KEY on its own, but we pass it explicitly
        # so the key always comes from our own config object.
        self.client = anthropic.Anthropic(api_key=api_key)
        self.default_model = default_model

    def _params(self, messages: list[dict], cfg: GenerationConfig) -> dict:
        model = cfg.model or self.default_model
        caps = model_caps("claude", model)

        params = {
            "model": model,
            "max_tokens": cfg.max_tokens,
            # `system` is a top-level parameter in Claude's API — it is NOT a
            # message with role "system" like in OpenAI's API.
            "system": cfg.system,
            "messages": _to_blocks(messages),
            "betas": [FALLBACK_BETA],
            "fallbacks": FALLBACK_MODE,
        }

        if caps["supports_thinking"]:
            # "adaptive" lets the model decide how much to think per request.
            # `display` defaults to "omitted" on this generation, which streams
            # thinking blocks with EMPTY text — asking for "summarized" is what
            # actually gives us something to render in the UI.
            params["thinking"] = {"type": "adaptive", "display": "summarized"}

        if caps["supports_effort"]:
            # effort controls how much the model thinks before answering.
            # "low" keeps a chat UI snappy; raise it for harder questions.
            params["output_config"] = {"effort": cfg.effort}

        if cfg.web_search and caps["supports_search"]:
            params["tools"] = [WEB_SEARCH_TOOL]

        return params

    def chat(self, messages: list[dict], cfg: GenerationConfig) -> ChatResult:
        params = self._params(messages, cfg)
        try:
            response = self.client.beta.messages.create(**params)
        except anthropic.BadRequestError:
            # Account not enrolled in the fallback beta — retry plainly.
            response = self.client.messages.create(**_without_beta(params))

        if response.stop_reason == "refusal":
            return ChatResult(text="I can't help with that request. Try rephrasing it.")

        # content is a list of blocks (text, thinking, tool_use, ...).
        # Always check .type before reading .text.
        return ChatResult(
            text="".join(b.text for b in response.content if b.type == "text"),
            thinking="".join(b.thinking for b in response.content if b.type == "thinking"),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def stream(self, messages: list[dict], cfg: GenerationConfig) -> Iterator[StreamChunk]:
        params = self._params(messages, cfg)
        started = False
        t0 = time.perf_counter()

        try:
            for chunk in self._stream_with(self.client.beta.messages, params):
                started = True
                yield self._stamp(chunk, params, cfg, t0)
        except anthropic.BadRequestError:
            # Only safe to restart if nothing reached the browser yet — a retry
            # after the first chunk would replay text the user already saw.
            if started:
                raise
            for chunk in self._stream_with(self.client.messages, _without_beta(params)):
                yield self._stamp(chunk, params, cfg, t0)

    def _stamp(self, chunk: StreamChunk, params: dict, cfg: GenerationConfig, t0: float) -> StreamChunk:
        """Attach the turn's metrics to the final chunk.

        Search runs on Anthropic's side here, so there is no tool time to
        report — the whole wall clock is time spent waiting on the model.
        """
        if not chunk.done:
            return chunk
        elapsed = round((time.perf_counter() - t0) * 1000)
        chunk.metrics = TurnMetrics(
            provider=self.name,
            model=params["model"],
            effort=cfg.effort if "output_config" in params else "",
            input_tokens=chunk.input_tokens or 0,
            output_tokens=chunk.output_tokens or 0,
            model_requests=1,
            total_ms=elapsed,
            model_ms=elapsed,
            search_backend="anthropic-hosted" if params.get("tools") else "",
        )
        return chunk

    @staticmethod
    def _stream_with(messages_api, params: dict) -> Iterator[StreamChunk]:
        """Split the raw event stream into reasoning chunks and answer chunks.

        `stream.text_stream` is the easy helper, but it yields only the answer —
        the thinking deltas are dropped. Iterating events is what lets the UI
        show the reasoning as it happens.
        """
        with messages_api.stream(**params) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    # Server-side search runs inside the same response, so the
                    # only sign it is happening is the block that opens for it.
                    kind = event.content_block.type
                    if kind == "server_tool_use":
                        yield StreamChunk(status="searching")
                    elif kind == "web_search_tool_result":
                        yield StreamChunk(status="searched")
                elif event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta":
                        yield StreamChunk(thinking=event.delta.thinking)
                    elif event.delta.type == "text_delta":
                        yield StreamChunk(text=event.delta.text)
            final = stream.get_final_message()

        yield StreamChunk(
            done=True,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )

    def list_models(self) -> set[str]:
        try:
            return {m.id for m in self.client.models.list(limit=100)}
        except Exception:  # noqa: BLE001 — availability info is a nice-to-have
            return set()


def _without_beta(params: dict) -> dict:
    plain = dict(params)
    plain.pop("betas", None)
    plain.pop("fallbacks", None)
    return plain


def _to_blocks(messages: list[dict]) -> list[dict]:
    """Turn our messages into Claude content blocks.

    Same idea as the OpenAI converter, different vocabulary: Claude calls them
    `image` and `document` blocks, and takes the base64 in a `source` object
    rather than a data URI.
    """
    out = []
    for m in messages:
        attachments = m.get("attachments") or []
        if not attachments:
            out.append({"role": m["role"], "content": m.get("content", "")})
            continue

        blocks: list[dict] = []
        if m.get("content"):
            blocks.append({"type": "text", "text": m["content"]})

        for a in attachments:
            if a["kind"] in ("image", "document"):
                blocks.append({
                    "type": "image" if a["kind"] == "image" else "document",
                    "source": {
                        "type": "base64",
                        "media_type": a["media_type"],
                        "data": a["data"],
                    },
                })
            else:
                blocks.append({
                    "type": "text",
                    "text": f"--- file: {a['name']} ---\n{a['data']}\n--- end of {a['name']} ---",
                })

        out.append({"role": m["role"], "content": blocks})
    return out
