"""Anthropic provider: `client.messages.parse` with schema-enforced output.

This is the call that lived inline in `judge.py` before providers existed; it is
moved here unchanged so switching `CLIVE_PROVIDER` is the only difference.
"""

from __future__ import annotations

from pydantic import BaseModel

from clive.providers.base import JudgeError, Provider, ProviderResult


class AnthropicProvider(Provider):
    name = "anthropic"
    default_model = "claude-opus-5"
    model_choices = [
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-haiku-4-5",
    ]
    api_key_env = "ANTHROPIC_API_KEY"

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
        try:
            import anthropic
        except ModuleNotFoundError:
            raise JudgeError("The `anthropic` package is not installed. Run `uv sync`.") from None

        client = anthropic.Anthropic()
        try:
            resp = client.messages.parse(
                model=model,
                max_tokens=max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=schema,
            )
        except anthropic.AuthenticationError:
            raise JudgeError(
                "The API key was rejected. Check ANTHROPIC_API_KEY in .env."
            ) from None
        except anthropic.NotFoundError:
            raise JudgeError(
                f"The model {model!r} does not exist or is not available to this key. "
                "Pick another model in the Prompt tab."
            ) from None
        except anthropic.RateLimitError as exc:
            retry_after = exc.response.headers.get("retry-after", "60")
            raise JudgeError(f"Rate limited; retry after {retry_after}s.") from None
        except anthropic.APIStatusError as exc:
            raise JudgeError(f"API error {exc.status_code}: {exc.message}") from None
        except anthropic.APIConnectionError:
            raise JudgeError("Could not reach the API. Check your connection.") from None

        if resp.stop_reason == "refusal":
            detail = getattr(resp, "stop_details", None)
            reason = getattr(detail, "explanation", None) or "no explanation given"
            raise JudgeError(f"The model declined to answer ({reason}).")
        if resp.stop_reason == "max_tokens":
            raise JudgeError(
                "Response hit max_tokens and the verdict list is truncated. "
                "Raise max_output_tokens in the Prompt tab, or lower effort."
            )

        return ProviderResult(
            parsed=resp.parsed_output,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
