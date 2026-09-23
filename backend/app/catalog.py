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

# Everything here goes through the Responses API, so every model below can be
# offered our web_search function tool. Only the GPT-5 family and the o-series
# accept the `reasoning` parameter — sending it to a GPT-4 model is a 400.
#
# Deliberately not listed: the *-chat-latest variants, which accept neither
# reasoning nor tools, and the -pro tiers, which are slow and costly enough
# that they belong in the free-text box rather than a dropdown.
OPENAI_MODELS = [
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 mini",
        "hint": "Fast, reasons — good default",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-5.5",
        "label": "GPT-5.5",
        "hint": "Newest flagship, slowest",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4",
        "hint": "Flagship, strong reasoning",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-5.4-nano",
        "label": "GPT-5.4 nano",
        "hint": "Cheapest that still reasons",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-5-mini",
        "label": "GPT-5 mini",
        "hint": "Previous generation, reasons",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "o4-mini",
        "label": "o4 mini",
        "hint": "o-series reasoning model",
        "supports_effort": True,
        "supports_thinking": True,
        "supports_search": True,
    },
    {
        "id": "gpt-4o",
        "label": "GPT-4o",
        "hint": "Strong, instant — no reasoning",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o mini",
        "hint": "Fastest and cheapest overall",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
    {
        "id": "gpt-4.1",
        "label": "GPT-4.1",
        "hint": "Long context — no reasoning",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
    {
        "id": "gpt-4.1-mini",
        "label": "GPT-4.1 mini",
        "hint": "Long context, fast",
        "supports_effort": False,
        "supports_thinking": False,
        "supports_search": True,
    },
]

# kie.ai's Codex gateway, straight from its /models endpoint. Every model
# there takes all five effort levels and accepts images — but none of them
# return a reasoning SUMMARY (`default_reasoning_summary` is "none" and asking
# for one changes nothing), so `supports_thinking` is False across the board
# while `supports_effort` is True. The two flags are not the same question:
# one is "does the dial work", the other is "do we get text to show".
#
# Search is our own function tool, run in this process, exactly as for OpenAI.
#
# `supports_images` is different in kind from the flags above it: it is not a
# parameter the model accepts but a HOSTED tool the gateway runs, drawing with
# gpt-image-2-codex and handing back finished PNG bytes. Verified working on
# every model here.
KIE_MODELS = [
    {
        "id": "gpt-6-astra",
        "label": "GPT-6 Astra",
        "hint": "Most capable — 272k context, 1M max",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
    },
    {
        "id": "gpt-5-6-sol",
        "label": "GPT-5.6 Sol",
        "hint": "gpt-5-6 family — 272k context",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
    },
    {
        "id": "gpt-5-6-terra",
        "label": "GPT-5.6 Terra",
        "hint": "gpt-5-6 family — 272k context",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
    },
    {
        "id": "gpt-5-6-luna",
        "label": "GPT-5.6 Luna",
        "hint": "gpt-5-6 family — 272k context",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
    },
    {
        "id": "gpt-5-5",
        "label": "GPT-5.5",
        "hint": "Previous flagship",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
    },
    {
        "id": "gpt-5-4",
        "label": "GPT-5.4",
        "hint": "Long context — 1M max",
        "supports_effort": True,
        "supports_thinking": False,
        "supports_search": True,
        "supports_images": True,
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
    "kie": {
        "label": "GPT-6",
        # Named for where the request actually goes, not for who trained the
        # model — the key, the billing and the outage page are all kie.ai's.
        "vendor": "kie.ai",
        "models": KIE_MODELS,
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
