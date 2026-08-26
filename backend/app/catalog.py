"""What the configuration panel is allowed to offer.

Curated lists live here rather than in the UI, so the frontend never has to
know provider-specific details. `/api/config` also cross-checks these ids
against each provider's live models endpoint and marks what your key can
actually use.

`supports_effort` / `supports_thinking` are per *model*, not per provider —
Claude's reasoning parameters are not uniform across the family, and sending
one to a model that does not accept it is a 400, not a silent no-op.
"""

EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

CLAUDE_MODELS = [
    {
        "id": "claude-opus-5",
        "label": "Opus 5",
        "hint": "Most capable",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "claude-sonnet-5",
        "label": "Sonnet 5",
        "hint": "Balanced",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "claude-haiku-4-5",
        "label": "Haiku 4.5",
        "hint": "Fastest, cheapest — no reasoning",
        # Haiku 4.5 predates adaptive thinking and rejects `effort` outright.
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": False,
    },
    {
        "id": "claude-opus-4-8",
        "label": "Opus 4.8",
        "hint": "Previous flagship",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
]

# Everything here goes through the Responses API, which supports web search on
# every model. Only the GPT-5 family reasons; the GPT-4 models answer directly.
OPENAI_MODELS = [
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 mini",
        "hint": "Fast, reasons",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-5-mini",
        "label": "GPT-5 mini",
        "hint": "Reasons, cheaper",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o mini",
        "hint": "Fast, cheap — no reasoning",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
    {
        "id": "gpt-4.1-mini",
        "label": "GPT-4.1 mini",
        "hint": "Long context — no reasoning",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
]

PROVIDERS = {
    "claude": {
        "label": "Claude",
        "vendor": "Anthropic",
        "models": CLAUDE_MODELS,
        # True if *any* model here has the dial; the panel greys it out
        # per-model using the flags above.
        "supports_effort": True,
    },
    "openai": {
        "label": "OpenAI",
        "vendor": "OpenAI",
        "models": OPENAI_MODELS,
        "supports_effort": True,
    },
}

# Fallback for a model id typed into the panel's free-text box: assume the
# current generation, since that is what a hand-typed id almost always is.
_UNKNOWN_MODEL = {
    "supports_effort": True,
    "supports_thinking": True,
    "supports_search": True,
}


def model_caps(provider: str, model_id: str) -> dict:
    """Which reasoning / search parameters this model accepts.

    Sending one to a model that does not take it is a 400, not a no-op, so
    every provider checks here before building its request.
    """
    for m in PROVIDERS.get(provider, {}).get("models", []):
        if m["id"] == model_id:
            return m
    return _UNKNOWN_MODEL
