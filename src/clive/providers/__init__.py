"""Provider registry. `get_provider()` resolves `CLIVE_PROVIDER` to an instance.

Importing this package is cheap: the concrete modules pull their vendor SDK only
inside `judge_json`, so `get_provider().default_model` works without `anthropic`
or `openai` installed.
"""

from __future__ import annotations

from clive import config
from clive.providers.anthropic import AnthropicProvider
from clive.providers.base import JudgeError, Provider, ProviderResult
from clive.providers.deepseek import DeepSeekProvider

__all__ = ["JudgeError", "Provider", "ProviderResult", "REGISTRY", "get_provider"]

REGISTRY: dict[str, type[Provider]] = {
    AnthropicProvider.name: AnthropicProvider,
    DeepSeekProvider.name: DeepSeekProvider,
}


def get_provider(name: str | None = None) -> Provider:
    """The provider named by `name`, or by `CLIVE_PROVIDER` when `name` is None."""
    key = (name or config.PROVIDER).lower()
    try:
        return REGISTRY[key]()
    except KeyError:
        raise JudgeError(
            f"Unknown provider {key!r}. Set CLIVE_PROVIDER to one of: "
            f"{', '.join(sorted(REGISTRY))}."
        ) from None
