"""Token usage and cost estimates.

Prices are USD per million tokens, from Anthropic's published pricing as of 2026-10-06. They are ESTIMATES:
they drift, so check them against the provider's current pricing before relying on a budget cap. A model
that is not in the table is priced like the default model and flagged as estimated.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:  # 5-minute cache writes cost 1.25x the input price
        return self.input * 1.25


PRICES: dict[str, Price] = {
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01),
    "claude-haiku-4-5": Price(input=1.00, output=5.00, cache_read=0.10),
}
DEFAULT_PRICE = PRICES["claude-sonnet-5-5"]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, api_usage) -> None:
        """Accumulate an API usage object (missing or None fields count as zero)."""
        self.input_tokens += getattr(api_usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(api_usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(api_usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(api_usage, "cache_creation_input_tokens", 0) or 0


def cost_usd(model: str, usage: Usage) -> float:
    p = PRICES.get(model, DEFAULT_PRICE)
    total = (usage.input_tokens * p.input + usage.output_tokens * p.output
             + usage.cache_read_tokens * p.cache_read + usage.cache_write_tokens * p.cache_write)
    return total / 1_000_000


def usage_record(model: str, usage: Usage) -> dict:
    return {
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens, "cache_write_tokens": usage.cache_write_tokens,
        "cost_usd": cost_usd(model, usage), "price_known": model in PRICES,
    }
