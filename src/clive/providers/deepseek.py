"""DeepSeek provider: the OpenAI SDK pointed at `api.deepseek.com`.

DeepSeek's API is OpenAI-compatible but has no schema-enforced structured
output and no `effort` / adaptive-thinking knob. `deepseek-chat` supports JSON
mode (`response_format={"type": "json_object"}`); `deepseek-reasoner` rejects
that parameter, so for it we rely on the preamble's "Return JSON only"
instruction plus `_extract_json` to peel off any fences or stray prose. Reply
validation is done here against the pydantic schema.

Reasoning depth is chosen by pinning `model.id: deepseek-reasoner` in the phase
YAML — there is no `effort` lever to pull.
"""

from __future__ import annotations

import pydantic
from pydantic import BaseModel

from clive.providers.base import JudgeError, Provider, ProviderResult

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(Provider):
    name = "deepseek"
    default_model = "deepseek-chat"
    model_choices = ["deepseek-chat", "deepseek-reasoner"]
    api_key_env = "DEEPSEEK_API_KEY"

    def judge_json(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_output_tokens: int,
        effort: str,  # DeepSeek has no effort knob; accepted and ignored.
        schema: type[BaseModel],
    ) -> ProviderResult:
        try:
            import openai
        except ModuleNotFoundError:
            raise JudgeError("The `openai` package is not installed. Run `uv sync`.") from None

        client = openai.OpenAI(api_key=self.api_key(), base_url=DEEPSEEK_BASE_URL)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # json_object mode is unsupported on deepseek-reasoner.
        if not model.startswith("deepseek-reasoner"):
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = client.chat.completions.create(**kwargs)
        except openai.AuthenticationError:
            raise JudgeError(
                "The API key was rejected. Check DEEPSEEK_API_KEY in .env."
            ) from None
        except openai.NotFoundError:
            raise JudgeError(
                f"The model {model!r} does not exist or is not available to this key. "
                "Pick another model in the Prompt tab."
            ) from None
        except openai.RateLimitError as exc:
            retry_after = "60"
            if exc.response is not None:
                retry_after = exc.response.headers.get("retry-after", "60")
            raise JudgeError(f"Rate limited; retry after {retry_after}s.") from None
        except openai.APIStatusError as exc:
            raise JudgeError(f"API error {exc.status_code}: {exc.message}") from None
        except openai.APIConnectionError:
            raise JudgeError("Could not reach the API. Check your connection.") from None

        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise JudgeError(
                "Response hit max_tokens and the verdict list is truncated. "
                "Raise max_output_tokens in the Prompt tab."
            )
        if choice.finish_reason == "content_filter":
            raise JudgeError("The model declined to answer (content filtered).")

        text = choice.message.content or ""
        try:
            parsed = schema.model_validate_json(_extract_json(text))
        except (ValueError, pydantic.ValidationError) as exc:
            raise JudgeError(
                f"DeepSeek did not return valid {schema.__name__} JSON: {str(exc)[:200]}"
            ) from None

        usage = resp.usage
        return ProviderResult(
            parsed=parsed,
            model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def _extract_json(text: str) -> str:
    """The outermost `{...}` span of `text`, with any markdown fence stripped.

    JSON mode returns a bare object, but deepseek-reasoner is only asked for JSON
    in prose and sometimes wraps it in a ```json fence or a sentence. Raises
    ValueError when there is no object to be found.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s[3:]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    return s[start : end + 1]
