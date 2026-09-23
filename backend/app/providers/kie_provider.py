"""Kie provider — GPT-6 Astra and the gpt-5-6 family, via kie.ai.

kie.ai re-publishes OpenAI's Responses API verbatim at
`https://api.kie.ai/codex/v1`, so this is the OpenAI provider pointed
somewhere else: same SDK, same request shape, same agent loop, same tools.
Everything below is the short list of places where the gateway differs.

Why it is worth having: these are the Codex-tier models (GPT-6 Astra tops the
list at a 272k context, 1.05M maximum) reachable with one flat key and no
OpenAI account, billed in kie.ai credits rather than per token. Good for
trying a model the OpenAI key cannot reach.

Three gateway quirks, all handled here rather than in the base class:

  1. It STREAMS BY DEFAULT. Omit `stream` and it answers `text/event-stream`
     even for a plain create() — which the SDK then hands back as a raw
     string, not a Response. `create_extras` pins `stream=False`.
  2. It returns NO REASONING SUMMARIES. The models reason (and report
     `reasoning_tokens`), and every one of them takes the five-level effort
     dial, but `default_reasoning_summary` is "none" and asking for "auto"
     changes nothing — no reasoning block ever comes back. So the catalog
     marks them `supports_effort` without `supports_thinking`, and the
     Reasoning pane simply stays empty.
  3. It IGNORES `max_output_tokens`, echoing it back as null. Harmless — the
     base class still sends it, and a gateway that starts honouring it would
     be honouring the right number.
  4. It reports SOME FAILURES WITH HTTP 200 and its own error envelope —
     `{"code": 402, "msg": "Credits insufficient …", "data": null}` — instead
     of a status code. The SDK sees a 200, parses it as a Response with every
     field empty, and hands back something that looks like a successful turn
     in which the model said nothing. `_check` catches that and says what
     actually happened; without it the first symptom is a TypeError on a null
     `output`, which points nowhere near the real cause.
  5. Its ERROR FRAMES ARE MALFORMED SSE — two `event: error` lines sharing one
     `data:` line. The SDK's parser reaches the second with nothing to read
     and dies on `json.loads("")`, so a plain upstream hiccup surfaces as a
     bare JSONDecodeError with no hint of its origin. `_should_retry` treats
     that as the transient failure it always is.

Web search is the same function tool the OpenAI provider uses, run in this
process, so the search-backend picker and the agent trace keep working.
kie.ai also exposes OpenAI's *hosted* `{"type": "web_search"}` tool on these
models — it works, but it hides the loop and takes the backend choice away,
which is the opposite of what the trace panel is for.

IMAGE GENERATION is the one place a hosted tool is the only option, and it is
offered: `{"type": "image_generation"}` draws with `gpt-image-2-codex` and
returns finished PNG bytes inline. There is nothing to run locally, so it
never touches the tool loop — the provider just watches for the finished
block. See `_params` below and `OpenAIProvider._images`.
"""

import json

from openai import OpenAI

from ..catalog import model_caps
from .base import GenerationConfig
from .openai_provider import TRUNCATED_STREAM, OpenAIProvider

# The Codex-compatible base path. Note `/codex/v1`, not `/v1`: kie.ai serves
# several unrelated APIs from the same host.
KIE_BASE_URL = "https://api.kie.ai/codex/v1"


class KieProvider(OpenAIProvider):
    # Its own name, so `model_caps` reads the Kie catalog entry rather than
    # OpenAI's — the model ids do not overlap, but the capability flags differ.
    name = "kie"

    # See quirk 1 above. Only reaches the non-streamed `responses.create`;
    # `responses.stream` sets `stream` itself.
    create_extras = {"stream": False}

    def __init__(self, api_key: str, default_model: str, base_url: str = KIE_BASE_URL) -> None:
        if not api_key:
            raise RuntimeError("KIE_API_KEY is missing — set it in backend/.env")
        # Deliberately not calling super().__init__: it builds a client with no
        # base_url and raises about the wrong environment variable.
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.default_model = default_model

    @staticmethod
    def _stream_refusal(stream) -> str | None:
        """The error envelope this gateway sends instead of an SSE body.

        Out of credits, kie.ai answers the STREAMING endpoint with HTTP 200
        and a plain JSON body — no `event:` lines anywhere. Left alone, the
        SDK's parser finds no events and reports only that the terminal event
        never came, which names the symptom and hides the cause; the three
        retries that follow buy nothing, because a refusal does not expire.

        Content type is the tell, and this runs before the SSE decoder has
        touched the body — afterwards httpx raises StreamConsumed and the
        message is gone for good. Reaching for the SDK's private response is
        deliberate but fully guarded: anything unexpected returns None and the
        caller carries on exactly as it did before.
        """
        raw = getattr(stream, "_response", None)
        if raw is None or "application/json" not in raw.headers.get("content-type", ""):
            return None

        try:
            body = json.loads(raw.read())
            message = body.get("msg") or body.get("message")
        except Exception:  # noqa: BLE001 — a guess that failed is just no guess
            return None

        if not message:
            return None
        return f"kie.ai rejected the request (code {body.get('code')}): {message}"

    @staticmethod
    def _check(response) -> None:
        """Turn this gateway's 200-with-an-error-body into a real exception.

        See quirk 4. A genuine response always carries `output` (an empty list
        at worst), so `None` means the body was never a response at all — the
        SDK has parsed an error envelope into an empty Response and the real
        message is sitting in the unmodelled extra fields.
        """
        if getattr(response, "output", None) is not None:
            return

        extra = getattr(response, "model_extra", None) or {}
        message = extra.get("msg") or extra.get("message")
        code = extra.get("code")
        if message:
            raise RuntimeError(f"kie.ai rejected the request (code {code}): {message}")
        raise RuntimeError(
            "kie.ai returned an empty response with no error message."
        )

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """As the base class, plus this gateway's broken error frames.

        See quirk 4 in the module docstring. A JSONDecodeError can only come
        out of the SSE parser here — we send no JSON of our own for it to
        choke on — so it always means "the gateway dropped the stream", which
        is exactly what a retry is for. Image generation is where it shows up:
        those turns are the long ones, so they meet more upstream restarts.
        """
        if isinstance(exc, json.JSONDecodeError):
            return True
        # A stream that ended with no terminal event AND nothing to salvage —
        # `stream()` keeps the output items when there are any, so reaching
        # here means the drop came before the model produced anything.
        if isinstance(exc, RuntimeError) and TRUNCATED_STREAM in str(exc):
            return True
        return OpenAIProvider._should_retry(exc)

    def _params(self, messages: list[dict], cfg: GenerationConfig) -> dict:
        """The OpenAI request, plus the hosted image tool when it is wanted."""
        params = super()._params(messages, cfg)

        if cfg.image_gen and model_caps(self.name, params["model"]).get("supports_images"):
            # Appended to whatever function tools the base class offered, not
            # instead of them: a turn can legitimately search for a reference
            # and then draw. `size` and `quality` are left at "auto" so the
            # model picks a shape that suits the subject.
            params["tools"] = [*params.get("tools", []), {"type": "image_generation"}]

        return params
