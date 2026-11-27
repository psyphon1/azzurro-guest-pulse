"""Settings for the optional LLM layer, read from the environment. No key means the layer is off."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-haiku-5-5"      # small and cheap: batch tagging and three-bullet summaries
ENRICH_PROMPT_VERSION = "enrich-v1"     # bump when the enrichment prompt or schema changes; old rows are kept
SUMMARY_PROMPT_VERSION = "summary-v1"

# US dollars per million tokens (input, output), used only for the cost line a run prints.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


@dataclass(frozen=True)
class LLMSettings:
    api_key: str | None
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


def load_settings(env: dict[str, str] | None = None) -> LLMSettings:
    env = os.environ if env is None else env
    key = (env.get("ANTHROPIC_API_KEY") or "").strip() or None
    model = (env.get("LLM_MODEL") or "").strip() or DEFAULT_MODEL
    return LLMSettings(api_key=key, model=model)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated US dollars for one call, or None when the model's price is not in the table."""
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
