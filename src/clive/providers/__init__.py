"""Provider registry and resolution.

`get_provider()` picks a concrete provider by, in order: an explicit `name`; the
provider whose model space claims a given `model` id (a phase's `model.id`); or
`CLIVE_PROVIDER`. So the phase's pinned model decides where its judge call goes,
and `CLIVE_PROVIDER` is only the default for a phase that pins no model.

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


def _provider_for_model(model: str) -> type[Provider] | None:
    return next((p for p in REGISTRY.values() if p.owns_model(model)), None)


def get_provider(name: str | None = None, *, model: str | None = None) -> Provider:
    """Resolve a provider.

    Precedence: an explicit `name`; else the provider whose model space claims
    `model`; else `CLIVE_PROVIDER`.
    """
    if name:
        key = name.lower()
    elif model and (owner := _provider_for_model(model)) is not None:
        return owner()
    else:
        key = config.PROVIDER.lower()
    try:
        return REGISTRY[key]()
    except KeyError:
        raise JudgeError(
            f"Unknown provider {key!r}. Set CLIVE_PROVIDER to one of: "
            f"{', '.join(sorted(REGISTRY))}."
        ) from None
