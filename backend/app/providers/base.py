"""The contract every provider implements.

The rest of the app only knows about `ChatProvider`, so switching between
Claude and OpenAI — or changing model / effort / system prompt from the UI —
never touches the routing code.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


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


@dataclass
class ChatResult:
    text: str
    thinking: str = ""  # summarized reasoning, "" if the model produced none
    input_tokens: int | None = None
    output_tokens: int | None = None


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
