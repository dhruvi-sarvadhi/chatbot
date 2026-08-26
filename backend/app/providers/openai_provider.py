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
from ..tools import SEARCH_TOOL_SCHEMA, web_search
from .base import ChatProvider, ChatResult, GenerationConfig, StreamChunk

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
            "input": messages,
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
    def _run_tools(output, items: list, clock=None) -> Iterator[StreamChunk]:
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

            if result is None:
                result = (
                    web_search(args.get("query", ""))
                    if block.name == "web_search"
                    else f"Unknown tool: {block.name}"
                )

            if clock:
                pages = result.count("--- Page content")
                yield StreamChunk(trace={
                    "step": "tool_result",
                    "label": f"{len(result):,} chars · {pages} page(s) read",
                    "detail": result[:TRACE_PREVIEW],
                    "ms": clock(),
                })

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
            for _ in self._run_tools(response.output, results):
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

            if final.usage:
                sent += final.usage.input_tokens
                received += final.usage.output_tokens

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
            yield from self._run_tools(final.output, results, clock)
            if not results:
                yield StreamChunk(trace={
                    "step": "answer",
                    "label": "No more tools requested — this is the answer",
                    "detail": "",
                    "ms": clock(),
                })
                break

            yield StreamChunk(status="searched")
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

        yield StreamChunk(done=True, input_tokens=sent, output_tokens=received)

    def list_models(self) -> set[str]:
        try:
            return {m.id for m in self.client.models.list()}
        except Exception:  # noqa: BLE001 — availability info is a nice-to-have
            return set()
