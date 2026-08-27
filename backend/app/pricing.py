"""Token prices, for turning usage into money.

Prices move and vary by account, so this table is data, not truth: check it
against the provider's pricing page before trusting a number it produces.
Anything missing here reports no cost rather than a guessed one — a wrong
cost figure is worse than none, because it looks authoritative.

Units: US dollars per million tokens.
"""

# (input, output) $/1M tokens.
PRICING: dict[str, tuple[float, float]] = {
    # Anthropic — from Anthropic's published API rates.
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI — fill these in from https://openai.com/api/pricing and they will
    # start appearing in the analytics strip. Left out on purpose rather than
    # seeded with numbers that might be stale.
    # "gpt-5.4-mini": (0.00, 0.00),
    # "gpt-4o-mini": (0.00, 0.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars for one turn, or None when the model is not priced above."""
    rates = PRICING.get(model)
    if not rates:
        return None
    per_in, per_out = rates
    return (input_tokens * per_in + output_tokens * per_out) / 1_000_000
