"""Provider selection, key lookup, and the DeepSeek JSON path — no network."""

from __future__ import annotations

import types

import pytest

from clive import config
from clive.judge import JudgeResult
from clive.providers import REGISTRY, JudgeError, get_provider
from clive.providers.anthropic import AnthropicProvider
from clive.providers.deepseek import DeepSeekProvider, _extract_json

VALID_RESULT = '{"verdicts": [{"criterion_id": "c1", "verdict": "PASS", "evidence": "x", "confidence": "high"}]}'


# --------------------------------------------------------------------- selection


def test_get_provider_by_name():
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
    assert isinstance(get_provider("deepseek"), DeepSeekProvider)
    assert isinstance(get_provider("DeepSeek"), DeepSeekProvider)  # case-insensitive


def test_get_provider_follows_config(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "deepseek")
    assert isinstance(get_provider(), DeepSeekProvider)


def test_get_provider_unknown_name_lists_valid():
    with pytest.raises(JudgeError) as exc:
        get_provider("gpt5")
    for name in REGISTRY:
        assert name in str(exc.value)


# ----------------------------------------------------------------------- api key


def test_has_api_key_reads_named_env(monkeypatch):
    provider = DeepSeekProvider()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert provider.has_api_key() is False
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert provider.has_api_key() is True
    assert provider.api_key() == "sk-test"


# ------------------------------------------------------------------ _extract_json


@pytest.mark.parametrize(
    "raw",
    [
        VALID_RESULT,
        f"```json\n{VALID_RESULT}\n```",
        f"```\n{VALID_RESULT}\n```",
        f"Here is the verdict list: {VALID_RESULT}",
    ],
)
def test_extract_json_recovers_object(raw):
    assert JudgeResult.model_validate_json(_extract_json(raw)).verdicts[0].verdict == "PASS"


def test_extract_json_without_object_raises():
    with pytest.raises(ValueError):
        _extract_json("I am unable to produce that.")


# ------------------------------------------------------------ deepseek judge_json


class _FakeCompletions:
    def __init__(self, response, sink):
        self._response = response
        self._sink = sink

    def create(self, **kwargs):
        self._sink.update(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response, sink):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(response, sink))


def _fake_response(content: str, finish_reason: str = "stop"):
    return types.SimpleNamespace(
        model="deepseek-chat",
        choices=[
            types.SimpleNamespace(
                finish_reason=finish_reason,
                message=types.SimpleNamespace(content=content),
            )
        ],
        usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=22),
    )


@pytest.fixture
def deepseek(monkeypatch):
    """DeepSeekProvider with a captured, offline OpenAI client."""
    import openai

    sink: dict = {}

    def install(content: str, finish_reason: str = "stop"):
        response = _fake_response(content, finish_reason)
        monkeypatch.setattr(
            openai, "OpenAI", lambda **kw: _FakeClient(response, sink)
        )
        return sink

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    return DeepSeekProvider(), install


def _call(provider, model="deepseek-chat"):
    return provider.judge_json(
        system="sys",
        user="usr",
        model=model,
        max_output_tokens=1000,
        effort="high",
        schema=JudgeResult,
    )


def test_judge_json_parses_and_reports_usage(deepseek):
    provider, install = deepseek
    install(VALID_RESULT)
    result = _call(provider)
    assert isinstance(result.parsed, JudgeResult)
    assert result.parsed.verdicts[0].criterion_id == "c1"
    assert (result.input_tokens, result.output_tokens) == (11, 22)
    assert result.model == "deepseek-chat"


def test_judge_json_uses_json_mode_for_chat(deepseek):
    provider, install = deepseek
    sink = install(VALID_RESULT)
    _call(provider, model="deepseek-chat")
    assert sink["response_format"] == {"type": "json_object"}


def test_judge_json_skips_json_mode_for_reasoner(deepseek):
    provider, install = deepseek
    sink = install(VALID_RESULT)
    _call(provider, model="deepseek-reasoner")
    assert "response_format" not in sink


def test_judge_json_appends_target_schema_to_system_prompt(deepseek):
    provider, install = deepseek
    sink = install(VALID_RESULT)
    _call(provider, model="deepseek-chat")
    system = sink["messages"][0]["content"]
    # The phase system_prompt ("sys") is kept, and the JudgeResult shape is spelled
    # out after it — DeepSeek is never told the shape by the API.
    assert system.startswith("sys")
    assert '"verdicts"' in system and '"criterion_id"' in system
    # Also satisfies json_object mode's "prompt must contain 'json'" rule.
    assert "json" in system.lower()


def test_judge_json_appends_schema_for_reasoner_too(deepseek):
    provider, install = deepseek
    sink = install(VALID_RESULT)
    _call(provider, model="deepseek-reasoner")
    # reasoner skips response_format but still needs the shape described.
    assert "response_format" not in sink
    assert '"verdicts"' in sink["messages"][0]["content"]


def test_judge_json_malformed_content_raises_judge_error(deepseek):
    provider, install = deepseek
    install("sorry, no JSON here")
    with pytest.raises(JudgeError):
        _call(provider)


def test_judge_json_truncation_raises_judge_error(deepseek):
    provider, install = deepseek
    install(VALID_RESULT, finish_reason="length")
    with pytest.raises(JudgeError, match="max_tokens"):
        _call(provider)
