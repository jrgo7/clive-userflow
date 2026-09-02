"""The provider seam: one abstract call that turns a rendered prompt into a
validated `JudgeResult`, with each concrete provider owning its SDK.

`judge.py` builds the prompts and audits the reply; it never imports a vendor
SDK. A provider takes `system` / `user` text plus the model knobs and returns a
`ProviderResult`, having already translated its own auth, rate-limit, not-found,
connection, refusal, and truncation failures into `JudgeError`.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel


class JudgeError(RuntimeError):
    """A judging run failed for a reason worth showing the user verbatim.

    Defined here rather than in `judge.py` so a provider can raise it without
    importing its caller. `judge.py` re-exports it for existing callers.
    """


@dataclass
class ProviderResult:
    """What a provider hands back once the reply has parsed and validated."""

    parsed: BaseModel
    model: str
    input_tokens: int
    output_tokens: int


class Provider(ABC):
    #: Registry key, and the value `CLIVE_PROVIDER` is matched against.
    name: str
    #: Used when a phase YAML does not pin `model.id`.
    default_model: str
    #: Offered in the Studio's model dropdown. Not exhaustive — a phase YAML may
    #: name any model id the provider accepts.
    model_choices: list[str]
    #: Environment variable holding this provider's API key.
    api_key_env: str
    #: Model-id prefixes this provider serves. `get_provider(model=...)` routes a
    #: phase's `model.id` to the provider that claims it, so a phase pinning a
    #: `claude-*` model reaches Anthropic even when CLIVE_PROVIDER names DeepSeek.
    model_prefixes: tuple[str, ...] = ()

    @classmethod
    def owns_model(cls, model_id: str) -> bool:
        """Whether `model_id` belongs to this provider's model space."""
        m = (model_id or "").lower()
        return m in {c.lower() for c in cls.model_choices} or bool(
            cls.model_prefixes and m.startswith(cls.model_prefixes)
        )

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None

    def has_api_key(self) -> bool:
        return self.api_key() is not None

    @abstractmethod
    def judge_json(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_output_tokens: int,
        effort: str,
        schema: type[BaseModel],
    ) -> ProviderResult:
        """Make one call and return the reply parsed into `schema`.

        Implementations must raise `JudgeError` — never a bare SDK exception —
        for a rejected key, an unknown model, a rate limit, a dropped
        connection, a refusal, or a response truncated by the token cap.
        """
