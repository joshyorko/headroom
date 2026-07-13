"""Pure LiteLLM model-name resolution rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiteLLMModelPrefixRule:
    """Case-insensitive bare-model prefix mapping to a LiteLLM provider key."""

    model_prefix: str
    provider_prefix: str

    def candidate_for(self, model: str) -> str | None:
        if model.lower().startswith(self.model_prefix):
            return f"{self.provider_prefix}{model}"
        return None


# Aliases for models removed from LiteLLM's cost database (retired/renamed).
# Maps old model name -> current LiteLLM key that has equivalent pricing.
MODEL_ALIASES: dict[str, str] = {
    # Claude 3.5 Sonnet retired Feb 2026, pricing same as claude-sonnet-4-20250514
    "claude-3-5-sonnet-20241022": "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20240620": "claude-sonnet-4-20250514",
    # Claude 3 Sonnet retired
    "claude-3-sonnet-20240229": "claude-3-haiku-20240307",
    # ChatGPT exposes subscription variants with zero-priced rows; use the
    # canonical Codex list price for savings estimates.
    "gpt-5.3-codex-spark": "gpt-5.3-codex",
    "chatgpt/gpt-5.3-codex-spark": "gpt-5.3-codex",
    # DeepSeek retains these compatibility names, but LiteLLM's legacy rows
    # carry pre-V4 pricing and context limits.
    "deepseek-chat": "deepseek/deepseek-v4-flash",
    "deepseek-reasoner": "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-chat": "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-reasoner": "deepseek/deepseek-v4-flash",
}

# These aliases intentionally override an existing LiteLLM row rather than
# serving only as a fallback for a retired name.
MODEL_ALIAS_OVERRIDES = frozenset(
    {
        "gpt-5.3-codex-spark",
        "chatgpt/gpt-5.3-codex-spark",
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-reasoner",
    }
)


MODEL_PREFIX_RULES: tuple[LiteLLMModelPrefixRule, ...] = (
    LiteLLMModelPrefixRule("claude-", "anthropic/"),
    LiteLLMModelPrefixRule("gpt-", "openai/"),
    LiteLLMModelPrefixRule("o1-", "openai/"),
    LiteLLMModelPrefixRule("o3-", "openai/"),
    LiteLLMModelPrefixRule("o4-", "openai/"),
    LiteLLMModelPrefixRule("gemini-", "google/"),
    LiteLLMModelPrefixRule("minimax-", "minimax/"),
    LiteLLMModelPrefixRule("deepseek-", "deepseek/"),
)


PRICE_LOOKUP_PROVIDER_PREFIXES: tuple[str, ...] = (
    "openai/",
    "anthropic/",
    "google/",
    "mistral/",
    "deepseek/",
    "minimax/",
)


def resolution_candidates(model: str) -> tuple[str, ...]:
    """Return ordered LiteLLM keys to try for cost-per-token resolution."""
    alias = MODEL_ALIASES.get(model)
    prefixed = [
        candidate
        for rule in MODEL_PREFIX_RULES
        for candidate in (rule.candidate_for(model),)
        if candidate is not None
    ]
    candidates = [alias] if alias and model in MODEL_ALIAS_OVERRIDES else [model]
    if model.lower().startswith("deepseek-") and not (alias and model in MODEL_ALIAS_OVERRIDES):
        candidates = [*prefixed, *candidates]
    else:
        candidates.extend(prefixed)
    if alias and model not in MODEL_ALIAS_OVERRIDES:
        candidates.append(alias)
    return tuple(dict.fromkeys(candidates))


def pricing_lookup_candidates(model: str) -> tuple[str, ...]:
    """Return ordered LiteLLM model_cost keys to try for pricing lookup."""
    alias = MODEL_ALIASES.get(model)
    candidates = [alias] if alias and model in MODEL_ALIAS_OVERRIDES else [model]
    candidates.extend(f"{prefix}{model}" for prefix in PRICE_LOOKUP_PROVIDER_PREFIXES)
    if alias and model not in MODEL_ALIAS_OVERRIDES:
        candidates.append(alias)
    return tuple(dict.fromkeys(candidates))


def resolve_litellm_model_name(
    model: str,
    is_known_model: Callable[[str], bool],
) -> str:
    """Resolve ``model`` to the first candidate accepted by LiteLLM."""
    for candidate in resolution_candidates(model):
        if is_known_model(candidate):
            return candidate
    return model
