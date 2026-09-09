"""Grading one C submission against a problem's test cases.

The seam between a problem and an executor, and deliberately pure: plain data in,
plain data out, no filesystem and no HTTP -- so the Studio's sandbox grades a scratch
problem exactly as /student grades a saved one. That is the same property `judge()`
has, and for the same reason.

Two rules live here rather than in the caller:

  Hidden cases are stripped of everything but a pass/fail before they are returned.
  AnimoRank does this in its route (src/routes/api/practice-session/[id]/run), which
  is one forgetful caller away from a leak. Below the route, no caller can forget.

  Comparison normalises trailing whitespace. AnimoRank compares stdout strictly, and
  every problem in cases/problems/ stores its expected output without a trailing
  newline -- so a strict comparison would reject correct programs on all nine of
  them. Interior whitespace is still significant.
"""

from __future__ import annotations

from typing import Literal

from clive.executors import ExecutionRequest, Limits, get_executor

__all__ = ["COMPILE_ARGV", "RUN_ARGV", "SCOPES", "normalise", "grade"]

#: AnimoRank's compile line, verbatim, from
#: src/lib/testCase/testCase/programIOTestCase/compile.sh -- including -Werror, which
#: means an unused variable is a failed build. Kept for parity; `warnings` on the
#: result is what lets the page show a warning as its own state rather than as a
#: wrong answer.
COMPILE_ARGV = ["gcc", "-Werror", "-Wall", "-o", "program", "main.c", "-lm", "-lpthread"]

RUN_ARGV = ["./program"]

SCOPES = ("public", "all")


def normalise(text: str) -> str:
    """Trailing whitespace per line, then trailing blank lines. Nothing else."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def grade(
    problem: dict,
    code: str,
    scope: Literal["public", "all"] = "public",
    executor=None,
) -> dict:
    """Compile `code` once and run it against `problem`'s cases in `scope`.

    `executor` is injectable so the tests can supply canned runs; production passes
    nothing and gets whatever `get_executor` resolves for this host.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}; expected one of {', '.join(SCOPES)}.")

    public = list(problem.get("public_test_cases") or [])
    hidden = list(problem.get("hidden_test_cases") or []) if scope == "all" else []
    cases = [(c, False) for c in public] + [(c, True) for c in hidden]

    executor = executor or get_executor()
    result = executor.run(
        ExecutionRequest(
            files={"main.c": code},
            compile_argv=COMPILE_ARGV,
            run_argv=RUN_ARGV,
            stdins=[str(c.get("input", "")) for c, _ in cases],
            limits=Limits(),
        )
    )

    out = {
        "compiled": result.compiled,
        "compile_error": result.compile_error,
        "warnings": result.warnings,
        "passed": False,
        "counts": {"passed": 0, "failed": 0, "total": len(cases)},
        "cases": [],
        "executor": {"name": executor.name, "isolation": executor.isolation},
    }
    if not result.compiled:
        # Nothing ran, so there are no cases to report. `total` stays at the number
        # the student would have faced, which is what the page counts against.
        return out

    for (case, is_hidden), run in zip(cases, result.runs):
        expected = str(case.get("output", ""))
        ok = run.status == "ok" and normalise(run.stdout) == normalise(expected)
        out["counts"]["passed" if ok else "failed"] += 1

        if is_hidden:
            # Everything else about a hidden case stays on the server.
            out["cases"].append({"hidden": True, "passed": ok, "status": run.status})
        else:
            out["cases"].append(
                {
                    "hidden": False,
                    "passed": ok,
                    "status": run.status,
                    "input": str(case.get("input", "")),
                    "expected": expected,
                    "actual": run.stdout,
                    "stderr": run.stderr,
                    "duration_ms": run.duration_ms,
                }
            )

    out["passed"] = out["counts"]["failed"] == 0 and bool(cases)
    return out
