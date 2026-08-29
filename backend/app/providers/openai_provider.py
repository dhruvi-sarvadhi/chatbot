"""OpenAI provider — calls the Responses API with the official SDK.

Why not Chat Completions? Because it cannot carry the two things this app
shows. Reasoning tokens are billed there but the reasoning text is never
returned, and function tools cannot be combined with reasoning summaries.
The Responses API has both, and every model in the catalog accepts it.

Web search here is OUR function, not OpenAI's hosted tool: the model asks for
a search, this file runs it against a free provider, and the results go back
in a second request. That is a real agent loop — the hosted tool hides it and
charges for the privilege.
"""

import json
import logging
import time
from collections.abc import Iterator

from openai import OpenAI

from ..catalog import model_caps
from ..tools import SEARCH_TOOL_SCHEMA, run_search
from .base import ChatProvider, ChatResult, GenerationConfig, StreamChunk, TurnMetrics

log = logging.getLogger("chatbot")

# One question rarely needs more than a couple of lookups, and every extra
# turn is another full request. This is the stop that keeps a confused model
# from looping until the bill notices.
MAX_TOOL_TURNS = 3

# How much of a tool result to show in the trace. Enough to see what the model
# was actually handed; not so much that the debug panel becomes the page.
TRACE_PREVIEW = 700


class OpenAIProvider(ChatProvider):
    name = "openai"

    def __init__(self, api_key: str, default_model: str) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing — set it in backend/.env")
        self.client = OpenAI(api_key=api_key)
        self.default_model = default_model

    def _params(self, messages: list[dict], cfg: GenerationConfig) -> dict:
        model = cfg.model or self.default_model
        caps = model_caps("openai", model)

        params = {
            "model": model,
            # The Responses API takes the standing instruction as its own
            # argument — not as a message with role "system", the way Chat
            # Completions did.
            "instructions": cfg.system,
            "input": _to_input(messages),
            "max_output_tokens": cfg.max_tokens,
        }

        if caps["supports_thinking"]:
            # `summary` is the opt-in that makes the reasoning readable —
            # without it the model still reasons (and still bills you) but
            # returns no text to show.
            params["reasoning"] = {"effort": cfg.effort, "summary": "auto"}

        if cfg.web_search and caps["supports_search"]:
            # A plain function tool. The model can only ask for it — running
            # it is this process's job, in _run_tools below.
            params["tools"] = [{"type": "function", **SEARCH_TOOL_SCHEMA}]

        return params

    @staticmethod
    def _echo(block) -> dict:
        """One output block, reshaped so it can be sent back as input.

        The response carries read-only bookkeeping (`status`) that the input
        schema rejects outright — a 400, not a warning. Round-tripping a block
        means stripping what the server added on the way out.
        """
        item = block.model_dump(exclude_none=True)
        item.pop("status", None)
        return item

    @staticmethod
    def _run_tools(output, items: list, clock=None, backend: str = "auto",
                   metrics: TurnMetrics | None = None) -> Iterator[StreamChunk]:
        """Execute every tool call, appending results to `items`.

        Yields trace chunks as it goes, so the UI can show the call before the
        work starts and the result after — the pause in between is the tool
        actually running. Callers that do not want a trace pass no clock and
        drain the generator.

        Each call needs its result echoed with the same `call_id`, or the API
        rejects the follow-up request for having an unanswered call.
        """
        for block in output:
            if block.type != "function_call":
                continue

            try:
                args = json.loads(block.arguments)
            except json.JSONDecodeError:
                # Never string-match the arguments; if they will not parse,
                # tell the model so rather than guessing what it meant.
                args, result = {}, "Could not parse the tool arguments. Try calling it again."
            else:
                result = None

            if clock:
                yield StreamChunk(trace={
                    "step": "tool_call",
                    "label": block.name,
                    "detail": json.dumps(args, indent=2) if args else block.arguments,
                    "ms": clock(),
                })

            outcome = None
            tool_started = time.perf_counter()
            if metrics is not None:
                metrics.tool_calls += 1
            if result is None:
                if block.name == "web_search":
                    outcome = run_search(args.get("query", ""), backend)
                    result = outcome.text
                else:
                    result = f"Unknown tool: {block.name}"

            if metrics is not None:
                metrics.tool_ms += round((time.perf_counter() - tool_started) * 1000)
                if outcome:
                    metrics.search_backend = outcome.used

            if clock:
                yield StreamChunk(trace={
                    "step": "tool_result",
                    "label": _result_label(outcome, result),
                    "detail": _result_detail(outcome, result),
                    "ms": clock(),
                })
                if outcome:
                    # Surfaced outside the trace too, so the backend and its
                    # cost are visible without opening the debug panel.
                    won = next((r for r in outcome.runs if r.backend == outcome.used), None)
                    yield StreamChunk(
                        status=f"searched:{outcome.used}:{won.ms if won else 0}"
                    )

            items.append(
                {"type": "function_call_output", "call_id": block.call_id, "output": result}
            )

    def chat(self, messages: list[dict], cfg: GenerationConfig) -> ChatResult:
        params = self._params(messages, cfg)
        convo = list(params["input"])
        thinking, sent, received = [], 0, 0

        for _ in range(MAX_TOOL_TURNS + 1):
            response = self.client.responses.create(**{**params, "input": convo})
            if response.usage:
                sent += response.usage.input_tokens
                received += response.usage.output_tokens

            # Reasoning arrives as its own output block holding a list of
            # summary parts — not as a field on the message.
            thinking += [
                part.text
                for block in response.output
                if block.type == "reasoning"
                for part in block.summary
            ]

            results = []
            # Same executor as the streaming path; without a clock it yields
            # nothing, so this just runs the tools.
            for _ in self._run_tools(response.output, results, backend=cfg.search_backend):
                pass
            if not results:
                return ChatResult(
                    text=response.output_text,
                    thinking="".join(thinking),
                    input_tokens=sent,
                    output_tokens=received,
                )

            # The model's own call blocks must go back too, not just our
            # answers — they are what the results attach to.
            convo += [self._echo(b) for b in response.output] + results

        log.warning("gave up after %d tool turns", MAX_TOOL_TURNS)
        return ChatResult(
            text="I kept needing to look things up and ran out of tries. Try asking more narrowly.",
            thinking="".join(thinking),
            input_tokens=sent,
            output_tokens=received,
        )

    def stream(self, messages: list[dict], cfg: GenerationConfig) -> Iterator[StreamChunk]:
        """Stream, pausing to run tools, then stream again into the same reply.

        The user sees one continuous answer. Underneath it is several requests:
        the model asks for a search, we run it, and the next request continues
        the same turn with the results attached.
        """
        params = self._params(messages, cfg)
        convo = list(params["input"])
        sent = received = 0

        # Milliseconds since the turn began — every trace step is stamped with
        # this, so the gaps in the panel are the real waits.
        t0 = time.perf_counter()
        clock = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731

        metrics = TurnMetrics(
            provider=self.name,
            model=params["model"],
            effort=cfg.effort if "reasoning" in params else "",
        )

        for turn in range(MAX_TOOL_TURNS + 1):
            tools = params.get("tools") or []
            yield StreamChunk(trace={
                "step": "request",
                "label": f"Request {turn + 1} → {params['model']}",
                "detail": (
                    f"{len(convo)} input item(s), {len(tools)} tool(s) offered"
                    + (f": {', '.join(t['name'] for t in tools)}" if tools else "")
                ),
                "ms": clock(),
            })

            metrics.model_requests += 1
            model_started = time.perf_counter()

            with self.client.responses.stream(**{**params, "input": convo}) as stream:
                for event in stream:
                    match event.type:
                        case "response.reasoning_summary_text.delta":
                            yield StreamChunk(thinking=event.delta)
                        case "response.output_text.delta":
                            yield StreamChunk(text=event.delta)
                        case "response.output_item.added":
                            # Our own search is about to be requested — the UI
                            # should say so before the pause, not after it.
                            if getattr(event.item, "type", None) == "function_call":
                                yield StreamChunk(status="searching")
                final = stream.get_final_response()

            metrics.model_ms += round((time.perf_counter() - model_started) * 1000)

            if final.usage:
                sent += final.usage.input_tokens
                received += final.usage.output_tokens
                metrics.input_tokens += final.usage.input_tokens
                metrics.output_tokens += final.usage.output_tokens
                # Nested details are absent on some models, so read defensively.
                out_detail = getattr(final.usage, "output_tokens_details", None)
                in_detail = getattr(final.usage, "input_tokens_details", None)
                metrics.reasoning_tokens += getattr(out_detail, "reasoning_tokens", 0) or 0
                metrics.cached_tokens += getattr(in_detail, "cached_tokens", 0) or 0

            yield StreamChunk(trace={
                "step": "response",
                "label": "Model replied: " + ", ".join(b.type for b in final.output),
                "detail": (
                    f"{final.usage.input_tokens:,} in · {final.usage.output_tokens:,} out"
                    if final.usage else "usage unavailable"
                ),
                "ms": clock(),
            })

            results = []
            yield from self._run_tools(final.output, results, clock, cfg.search_backend, metrics)
            if not results:
                yield StreamChunk(trace={
                    "step": "answer",
                    "label": "No more tools requested — this is the answer",
                    "detail": "",
                    "ms": clock(),
                })
                break

            convo += [self._echo(b) for b in final.output] + results
        else:
            log.warning("gave up after %d tool turns", MAX_TOOL_TURNS)
            yield StreamChunk(trace={
                "step": "limit",
                "label": f"Stopped at the {MAX_TOOL_TURNS}-turn limit",
                "detail": "The model kept asking for tools. See MAX_TOOL_TURNS.",
                "ms": clock(),
            })
            yield StreamChunk(text="\n\n(Stopped after too many lookups.)")

        metrics.total_ms = clock()
        yield StreamChunk(
            done=True, input_tokens=sent, output_tokens=received, metrics=metrics
        )

    def list_models(self) -> set[str]:
        try:
            return {m.id for m in self.client.models.list()}
        except Exception:  # noqa: BLE001 — availability info is a nice-to-have
            return set()


def _result_label(outcome, result: str) -> str:
    """One line summarising what the search cost."""
    if outcome is None:
        return f"{len(result):,} chars"
    parts = [f"{r.backend} {r.ms / 1000:.1f}s" for r in outcome.runs]
    return f"{' vs '.join(parts)} · {outcome.used} used"


def _result_detail(outcome, result: str) -> str:
    """A comparison table when two backends ran, then what the model got."""
    if outcome is None:
        return result[:TRACE_PREVIEW]

    rows = [f"{'backend':<12}{'time':>8}{'chars':>9}{'sources':>9}{'pages':>7}"]
    for r in outcome.runs:
        pages = "—" if r.pages_read is None else str(r.pages_read)
        status = "" if r.ok else "  (failed)"
        rows.append(
            f"{r.backend:<12}{r.ms / 1000:>7.2f}s{r.chars:>9,}{r.sources:>9}{pages:>7}{status}"
        )
    rows.append("")
    rows.append(f"Fed to the model: {outcome.used}")
    rows.append("")
    rows.append(result[:TRACE_PREVIEW])
    return "\n".join(rows)


def _to_input(messages: list[dict]) -> list[dict]:
    """Turn our messages into Responses API input items.

    A message with no attachments stays a plain string, which keeps the common
    case simple. One with attachments becomes a list of typed content blocks —
    the text first, then the files, because the question is what tells the
    model what to look for.
    """
    items = []
    for m in messages:
        attachments = m.get("attachments") or []
        if not attachments:
            items.append({"role": m["role"], "content": m.get("content", "")})
            continue

        content: list[dict] = []
        if m.get("content"):
            content.append({"type": "input_text", "text": m["content"]})

        for a in attachments:
            if a["kind"] == "image":
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{a['media_type']};base64,{a['data']}",
                })
            elif a["kind"] == "document":
                content.append({
                    "type": "input_file",
                    "filename": a["name"],
                    "file_data": f"data:{a['media_type']};base64,{a['data']}",
                })
            else:
                # Already plain text — no upload, no extraction, no per-page
                # cost. Fenced so the model can tell file from question.
                content.append({
                    "type": "input_text",
                    "text": f"--- file: {a['name']} ---\n{a['data']}\n--- end of {a['name']} ---",
                })

        items.append({"role": m["role"], "content": content})
    return items
