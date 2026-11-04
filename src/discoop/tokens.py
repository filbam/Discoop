"""Token count estimation and formatting utilities for LLM prompts."""

import math


def estimate_tokens(text: str) -> int:
    """Rough heuristic estimate of LLM tokens (~4 characters per token)."""
    return math.ceil(len(text) / 4)


def format_tokens(n: int) -> str:
    """Format token count into a human-readable string (e.g. '850', '12.4k', '1.2M')."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"
