"""The tests-gated path through the student API.

No compiler and no network: the executor is stubbed, so what is under test is the
branching, the ordering, and the leak guard -- not gcc.
"""

from __future__ import annotations

import pytest

from clive import grade as grading
from clive import nudge as nudging
from clive import prompts
from clive.executors.base import ExecutionResult, RunOutcome
from clive.studio import student

CODE = "#include <stdio.h>\nint main(void){printf(\"3\\n\");return 0;}"


class StubExecutor:
    name, isolation = "stub", "container"

    def __init__(self, stdouts, compiled=True):
        self.stdouts, self.compiled = stdouts, compiled

    def run(self, request):
        if not self.compiled:
            return ExecutionResult(False, "main.c:1: error: boom", "", [])
        return ExecutionResult(
            True, "", "", [RunOutcome("ok", s, "", 0, 1) for s in self.stdouts]
        )


@pytest.fixture
def stub_executor(monkeypatch):
    """Installed into grade, which is where production resolves one."""
    holder = {}

    def install(stdouts, compiled=True):
        holder["e"] = StubExecutor(stdouts, compiled)
        monkeypatch.setattr(grading, "get_executor", lambda: holder["e"])
        return holder["e"]

    return install


@pytest.fixture
def no_judge(monkeypatch):
    """Fails loudly if the judge is called. Several tests assert it is not."""
    def boom(*a, **k):
        raise AssertionError("the judge was called on a submission whose tests failed")

    monkeypatch.setattr(student.judging, "judge", boom)


def submit_body(code=CODE):
    return {"phase_id": "implement", "problem_id": "count_vowels", "code": code,
            "artifact": {"code": code}, "attempt": 1}


def test_run_grades_public_cases_only(stub_executor):
    stub_executor(["3\n", "3\n", "0\n"])
    result = student.run({"problem_id": "count_vowels", "code": CODE})
    assert result["counts"]["total"] == 3
    assert result["passed"]


def test_run_never_returns_a_verdict_or_a_nudge(stub_executor):
    stub_executor(["3\n", "3\n", "0\n"])
    result = student.run({"problem_id": "count_vowels", "code": CODE})
    assert "verdicts" not in result
    assert "nudge" not in result


def test_a_failing_submission_does_not_call_the_judge(stub_executor, no_judge, monkeypatch):
    stub_executor(["9\n", "9\n", "9\n"])
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "0", "reason": "r",
                                         "nudge": "n", "failing": []})
    result = student.submit(submit_body())
    assert not result["passed"]
    assert result["test_run"]["counts"]["failed"] == 3
    assert result["nudge"]["summary"] == "s"
    assert result["verdicts"] == []


def test_a_compile_error_does_not_call_the_judge(stub_executor, no_judge, monkeypatch):
    stub_executor([], compiled=False)
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "compile", "reason": "r",
                                         "nudge": "n", "failing": []})
    result = student.submit(submit_body())
    assert not result["passed"]
    assert not result["test_run"]["compiled"]


def test_passing_every_case_passes_the_phase_and_judges_advisory(stub_executor, monkeypatch):
    stub_executor(["3\n", "3\n", "0\n"])
    criteria = prompts.load_criteria("implement")["criteria"]
    monkeypatch.setattr(student.judging, "judge", lambda *a, **k: {
        "verdicts": [{"criterion_id": c["id"], "verdict": "FAIL", "evidence": "",
                      "confidence": "low", "evidence_found": True} for c in criteria],
        "missing_ids": [],
    })
    result = student.submit(submit_body())
    assert result["passed"], "an advisory FAIL must never hold a tests-gated phase"
    assert result["blocking"] == []
    assert len(result["advisory_unmet"]) == len(criteria)


def test_a_failing_nudge_still_returns_the_test_results(stub_executor, monkeypatch):
    stub_executor(["9\n", "9\n", "9\n"])

    def boom(*a, **k):
        raise nudging.JudgeError("provider down")

    monkeypatch.setattr(student.nudging, "nudge_code", boom)
    result = student.submit(submit_body())
    assert result["nudge_error"] == "provider down"
    assert result["test_run"]["counts"]["failed"] == 3


def test_hidden_cases_are_graded_but_never_described(stub_executor, monkeypatch, tmp_path):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("demo", {
        "statement": "s\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET", "output": "42"}],
    })
    stub_executor(["1\n", "0\n"])
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "hidden", "reason": "r",
                                         "nudge": "n", "failing": []})
    body = submit_body()
    body["problem_id"] = "demo"
    result = student.submit(body)
    assert "SECRET" not in str(result)
    assert "42" not in str(result)


def test_problem_carries_starter_code_and_never_hidden_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("demo", {
        "statement": "s\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET", "output": "42"}],
        "starter_code": "int main(void){}",
    })
    out = student.problem("demo")
    assert out["problem"]["starter_code"] == "int main(void){}"
    assert "hidden_test_cases" not in out["problem"]
    assert "SECRET" not in str(out)


def test_boot_reports_the_executor():
    executor = student.boot()["executor"]
    assert set(executor) == {"available", "name", "isolation", "toolchain", "error"}
