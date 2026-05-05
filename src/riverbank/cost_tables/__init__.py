"""Cost tables for LLM token pricing.

Rates are in USD per 1 000 tokens (input, output).
A rate of (0.0, 0.0) means the model is free (local/Ollama).

These tables are used by the pipeline cost estimator and the
``riverbank runs`` cost dashboard.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Per-model cost table (USD / 1 000 tokens)
# ---------------------------------------------------------------------------

#: Maps model name (lower-case) to (input_rate_per_1k, output_rate_per_1k).
COST_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4-turbo-preview": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.001, 0.002),
    "gpt-3.5-turbo-0125": (0.0005, 0.0015),
    # Anthropic
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-5-haiku-20241022": (0.001, 0.005),
    "claude-3-opus-20240229": (0.015, 0.075),
    "claude-3-sonnet-20240229": (0.003, 0.015),
    "claude-3-haiku-20240307": (0.00025, 0.00125),
    # Google
    "gemini-1.5-pro": (0.00125, 0.005),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.0-pro": (0.0005, 0.0015),
    # Mistral
    "mistral-large-latest": (0.004, 0.012),
    "mistral-small-latest": (0.001, 0.003),
    "mistral-7b-instruct-v0.2": (0.00025, 0.00025),
    # Local / Ollama — always free
    "llama3.2": (0.0, 0.0),
    "llama3.2:3b": (0.0, 0.0),
    "llama3.2:1b": (0.0, 0.0),
    "llama3.1": (0.0, 0.0),
    "llama3.1:8b": (0.0, 0.0),
    "llama3.1:70b": (0.0, 0.0),
    "llama3": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "mixtral": (0.0, 0.0),
    "phi3": (0.0, 0.0),
    "gemma2": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "nomic-embed-text": (0.0, 0.0),
}


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model_name: str,
) -> float:
    """Return the estimated USD cost for a given token usage and model.

    Unknown models are treated as free (returns 0.0).
    """
    key = model_name.lower()
    input_rate, output_rate = COST_PER_1K_TOKENS.get(key, (0.0, 0.0))
    return (prompt_tokens / 1000.0 * input_rate) + (completion_tokens / 1000.0 * output_rate)


def format_cost(cost_usd: float) -> str:
    """Return a human-readable cost string, e.g. '$0.001234' or '$0.00 (free)'."""
    if cost_usd == 0.0:
        return "$0.00 (free)"
    if cost_usd < 0.0001:
        return f"${cost_usd:.6f}"
    return f"${cost_usd:.4f}"


__all__ = ["COST_PER_1K_TOKENS", "estimate_cost", "format_cost"]
