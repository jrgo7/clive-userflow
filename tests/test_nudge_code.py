"""The code nudge: what it may see, and what it must never see.

The hidden-case rule is the whole point of these tests. A nudge prompt is the one place
a hidden input could leak without any route returning it, because the model is handed
the failures directly.
"""

from __future__ import annotations

import pytest

from clive import nudge as nudging
from clive import prompts

PHASE = "implement"

TEST_RUN = {
    "compiled": True,
    "compile_error": "",
    "warnings": "",
    "passed": False,
    "counts": {"passed": 1, "failed": 2, "total": 3},
    "cases": [
        {"hidden": False, "passed": True, "status": "ok",
         "input": "Hello World", "expected": "3", "actual": "3\n"},
        {"hidden": False, "passed": False, "status": "ok",
         "input": "rhythm", "expected": "0", "actual": "1\n"},
        {"hidden": True, "passed": False, "status": "ok"},
    ],
}


class StubProvider:
    name, api_key_env, default_model = "stub", "STUB_KEY", "stub-1"
    model_choices = ["stub-1"]

    def __init__(self):
        self.user_prompt = None

    def has_api_key(self):
        return True

    def judge_json(self, system, user, model, max_output_tokens, effort, schema):
        self.user_prompt = user
        parsed = schema(summary="One case disagrees.", focus_id="1",
                        reason="It is the simplest.", nudge="What does y count as?")
        return type("R", (), {"parsed": parsed, "model": "stub-1",
                              "input_tokens": 1, "output_tokens": 1})()


@pytest.fixture
def stub(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr(nudging, "get_provider", lambda *a, **k: provider)
    return provider


def run_nudge(stub, test_run=None, code="int main(void){}"):
    return nudging.nudge_code(
        prompts.load_phase(PHASE),
        prompts.load_problem("count_vowels"),
        code,
        test_run or TEST_RUN,
        attempt=2,
        prior_artifacts=[{"label": "Design", "fields": [{"label": "Steps", "value": "1. Read"}]}],
    )


def test_returns_the_same_keys_as_the_criterion_nudge(stub):
    result = run_nudge(stub)
    assert set(result) == {"summary", "focus_id", "reason", "nudge", "failing"}


def test_only_failing_cases_are_listed(stub):
    result = run_nudge(stub)
    assert [f["id"] for f in result["failing"]] == ["1", "hidden"]


def test_the_prompt_sees_failing_public_io(stub):
    run_nudge(stub)
    assert "rhythm" in stub.user_prompt
    assert "1\n" in stub.user_prompt or "1" in stub.user_prompt


def test_the_prompt_never_sees_a_hidden_input(stub):
    """The rule that matters. A hidden case reaches the model as a count, never as I/O."""
    hidden_secret = "SECRET_HIDDEN_INPUT"
    test_run = dict(TEST_RUN)
    test_run["cases"] = TEST_RUN["cases"][:2] + [
        {"hidden": True, "passed": False, "status": "ok",
         "input": hidden_secret, "expected": "99", "actual": "0"},
    ]
    run_nudge(stub, test_run)
    assert hidden_secret not in stub.user_prompt
    assert "99" not in stub.user_prompt


def test_the_prompt_carries_the_students_design(stub):
    run_nudge(stub)
    assert "1. Read" in stub.user_prompt


def test_a_compile_error_is_nudged_on_instead_of_cases(stub):
    test_run = {
        "compiled": False, "compile_error": "main.c:4:5: error: expected ';'",
        "warnings": "", "passed": False,
        "counts": {"passed": 0, "failed": 0, "total": 3}, "cases": [],
    }
    result = run_nudge(stub, test_run)
    assert [f["id"] for f in result["failing"]] == ["compile"]
    assert "expected ';'" in stub.user_prompt


def test_nothing_failing_is_refused(stub):
    passing = {"compiled": True, "compile_error": "", "warnings": "", "passed": True,
               "counts": {"passed": 3, "failed": 0, "total": 3}, "cases": []}
    with pytest.raises(nudging.JudgeError):
        run_nudge(stub, passing)
