"""The contract every provider implements.

The rest of the app only knows about `ChatProvider`, so switching between
Claude and OpenAI — or changing model / effort / system prompt from the UI —
never touches the routing code.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class GenerationConfig:
    """Everything the config panel can change for a single request."""

    model: str
    system: str
    max_tokens: int
    effort: str = "low"
    # Let the model search the web when the answer needs current facts.
    # The provider runs the search itself — we never make the HTTP call.
    web_search: bool = False
    # Which search backend to use: auto / tavily / duckduckgo / compare.
    search_backend: str = "auto"
    # Let the model draw. Unlike web_search and clarix this is a HOSTED tool:
    # the provider generates the image on its own servers and hands back the
    # finished bytes, so there is nothing for our tool loop to run.
    image_gen: bool = False
    # Let the model reach the user's Clarix workspace. A provider still needs
    # a configured key on top of this — the flag can only take the tools away,
    # never conjure them.
    clarix: bool = True
    # This turn is a form coming back, so the answers are already resolved and
    # the only thing left to do is write them through. Nothing about that needs
    # the web, and gpt-4o-mini reliably searched it anyway — burning the whole
    # tool budget on "Week-september-task-list" instead of creating the task.
    # So the search tool is not offered on these turns at all: the surest way
    # to stop a model picking the wrong tool is not to hand it one.
    from_form: bool = False


@dataclass
class TurnMetrics:
    """What one answer cost, in tokens and in seconds.

    Recorded per turn rather than per request, because a single answer can be
    several requests plus tool work — and the interesting question is what the
    whole thing cost, not what one leg of it did.
    """

    provider: str = ""
    model: str = ""
    effort: str = ""

    input_tokens: int = 0
    output_tokens: int = 0
    # Thinking tokens, billed as output but not visible in the reply.
    reasoning_tokens: int = 0
    # Prompt prefix served from cache, billed at a lower rate.
    cached_tokens: int = 0

    # Shape of the loop: more than one request means tools ran.
    model_requests: int = 0
    tool_calls: int = 0

    total_ms: int = 0
    # Waiting on the provider vs waiting on our own tools. The split is the
    # whole point — one of the two is yours to optimise.
    model_ms: int = 0
    tool_ms: int = 0

    search_backend: str = ""


@dataclass
class ChatResult:
    text: str
    thinking: str = ""  # summarized reasoning, "" if the model produced none
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Same shape as StreamChunk.image, one entry per picture the model drew.
    images: list[dict] = field(default_factory=list)


@dataclass
class StreamChunk:
    """One piece of a streamed answer.

    A chunk carries exactly one of `thinking`, `text` or `status` — the reasoning
    stream and the answer stream are separate content blocks and the UI shows
    them in different places. Reasoning arrives first, then the answer; the
    provider emits a final `done` chunk carrying token usage, so the UI can
    show the cost of the turn that just finished.
    """

    text: str = ""
    thinking: str = ""
    # Transient activity for the UI: "searching" while a web lookup runs,
    # "searched" once results are back. Not part of the conversation.
    status: str = ""
    # One entry for the agent trace — a debugging view of the loop, not part
    # of the answer. Keys: step, label, detail, ms. See the providers.
    trace: dict | None = None
    # One finished image from a hosted image-generation tool, as
    # {"b64": ..., "output_format": ..., "size": ..., "revised_prompt": ...}.
    # The bytes stop at main.py, which writes them to disk and sends the
    # browser a URL — a few megabytes of base64 through the SSE stream would
    # stall every other chunk behind it.
    image: dict | None = None
    # A form for the user to fill in, rendered as a card in the transcript
    # instead of the model asking for each field in prose. Built by
    # tools/ask_form.py; the answers come back as the user's next message.
    form: dict | None = None
    # Set only on the final `done` chunk.
    metrics: TurnMetrics | None = None
    done: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatProvider(ABC):
    name: str
    default_model: str

    @abstractmethod
    def chat(self, messages: list[dict], cfg: GenerationConfig) -> ChatResult:
        """One request, one full answer."""

    @abstractmethod
    def stream(self, messages: list[dict], cfg: GenerationConfig) -> Iterator[StreamChunk]:
        """Yield the answer in small pieces as the model writes it."""

    @abstractmethod
    def list_models(self) -> set[str]:
        """Model ids this API key can actually use (empty set if unknown)."""
