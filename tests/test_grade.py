"""Grading: comparison semantics, scope, and the hidden-case rule.

No subprocess and no network -- a stub executor returns canned runs, because what is
under test is the comparison and the stripping, not the compiler.
"""

from __future__ import annotations

import pytest

from clive import grade
from clive.executors.base import ExecutionResult, RunOutcome


class StubExecutor:
    """Returns one canned RunOutcome per stdin, in order."""

    name, isolation = "stub", "container"

    def __init__(self, stdouts, compiled=True, compile_error="", warnings=""):
        self.stdouts, self.compiled = stdouts, compiled
        self.compile_error, self.warnings = compile_error, warnings
        self.seen = None

    def run(self, request):
        self.seen = request
        if not self.compiled:
            return ExecutionResult(False, self.compile_error, "", [])
        runs = [RunOutcome("ok", s, "", 0, 1) for s in self.stdouts]
        return ExecutionResult(True, "", self.warnings, runs)


PROBLEM = {
    "slug": "demo",
    "public_test_cases": [{"input": "a", "output": "1"}, {"input": "b", "output": "2"}],
    "hidden_test_cases": [{"input": "c", "output": "3"}],
}


def test_trailing_newline_does_not_fail_a_correct_program():
    """The load-bearing divergence from AnimoRank. Every problem in the corpus stores
    its expected output without a trailing newline, and every correct C program that
    uses printf("%d\\n", ...) emits one."""
    result = grade.grade(PROBLEM, "code", "public", StubExecutor(["1\n", "2\n"]))
    assert result["passed"]
    assert result["counts"] == {"passed": 2, "failed": 0, "total": 2}


def test_interior_whitespace_still_matters():
    problem = {"public_test_cases": [{"input": "", "output": "1 2"}], "hidden_test_cases": []}
    assert not grade.grade(problem, "code", "public", StubExecutor(["1  2\n"]))["passed"]


def test_trailing_blank_lines_are_ignored():
    problem = {"public_test_cases": [{"input": "", "output": "1"}], "hidden_test_cases": []}
    assert grade.grade(problem, "code", "public", StubExecutor(["1\n\n\n"]))["passed"]


def test_public_scope_does_not_run_hidden_cases():
    stub = StubExecutor(["1\n", "2\n"])
    grade.grade(PROBLEM, "code", "public", stub)
    assert stub.seen.stdins == ["a", "b"]


def test_all_scope_runs_every_case():
    stub = StubExecutor(["1\n", "2\n", "3\n"])
    result = grade.grade(PROBLEM, "code", "all", stub)
    assert stub.seen.stdins == ["a", "b", "c"]
    assert result["counts"]["total"] == 3


def test_hidden_cases_never_carry_their_io():
    stub = StubExecutor(["1\n", "2\n", "WRONG\n"])
    result = grade.grade(PROBLEM, "code", "all", stub)
    hidden = [c for c in result["cases"] if c["hidden"]]
    assert len(hidden) == 1
    assert not hidden[0]["passed"]
    assert set(hidden[0]) == {"hidden", "passed", "status"}
    assert "3" not in str(hidden[0])


def test_public_cases_carry_their_io():
    result = grade.grade(PROBLEM, "code", "public", StubExecutor(["1\n", "NOPE\n"]))
    second = result["cases"][1]
    assert second["input"] == "b"
    assert second["expected"] == "2"
    assert second["actual"] == "NOPE\n"
    assert not second["passed"]


def test_compile_failure_reports_no_cases():
    stub = StubExecutor([], compiled=False, compile_error="main.c:1: error: expected ';'")
    result = grade.grade(PROBLEM, "code", "all", stub)
    assert not result["compiled"]
    assert not result["passed"]
    assert result["cases"] == []
    assert "expected ';'" in result["compile_error"]


def test_warnings_are_carried_without_failing():
    stub = StubExecutor(["1\n", "2\n"], warnings="main.c:3: warning: unused variable")
    result = grade.grade(PROBLEM, "code", "public", stub)
    assert result["passed"]
    assert "unused variable" in result["warnings"]


def test_a_timeout_is_a_failed_case_not_an_exception():
    class Timeouts(StubExecutor):
        def run(self, request):
            return ExecutionResult(True, "", "", [RunOutcome("timeout", "", "", -1, 5000)] * 2)

    result = grade.grade(PROBLEM, "code", "public", Timeouts([]))
    assert not result["passed"]
    assert result["cases"][0]["status"] == "timeout"


def test_the_student_code_is_written_as_main_c():
    stub = StubExecutor(["1\n", "2\n"])
    grade.grade(PROBLEM, "int main(void){}", "public", stub)
    assert stub.seen.files == {"main.c": "int main(void){}"}


def test_unknown_scope_is_refused():
    with pytest.raises(ValueError):
        grade.grade(PROBLEM, "code", "everything", StubExecutor([]))
