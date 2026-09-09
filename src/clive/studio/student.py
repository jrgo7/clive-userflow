"""The student-facing API: the same engine as the Studio, shaped for the person
being taught rather than the person authoring the rubric.

The Studio hands the browser everything, because an author needs to see everything.
A student must not have all of it, and the difference is not cosmetic -- so it lives
here in the server rather than as restraint in the page:

  The rubric is never sent before it has been ruled on. `boot` returns phases without
  their criteria; a criterion's text reaches the browser only attached to a verdict on
  it, in `submit`. Shipping the whole rubric and hiding it in the page would put the
  checklist one devtools panel away from the student it is meant to make think.

  A problem's hidden test cases are the same rule applied to a compiler instead of a
  judge. `problem` never adds them -- its dict is built key by key rather than by
  copying the loaded YAML, so there is no wholesale copy for a future field to leak
  through -- and `run` fixes its scope to `"public"` in code, not from the request, so
  no request can turn the Run button into a way to read the hidden suite back one
  probe at a time.

  Prompts, model ids and token counts are stripped. They are the author's concern and
  they invite the student to argue with the judge rather than with the problem.

  The nudge is not a separate request. `submit` runs it in the same call whenever a
  gating criterion failed, so a page cannot render a failure without the guidance that
  is supposed to come with it, and a student cannot be left staring at a verdict list.

There is no session store here on purpose. This system has no user model yet, so the
browser holds the session and posts what it has; every function below is stateless and
judges the saved files on disk -- never a Sandbox scratch copy, which belongs to the
author's experiments and not to a student's transcript.
"""

from __future__ import annotations

from clive import grade as grading
from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import prompts
from clive.executors import ExecutorError, describe_toolchain, get_executor
from clive.providers import get_provider

__all__ = ["boot", "problem", "submit", "run", "hint"]


def boot() -> dict:
    """What the page needs before the student has done anything.

    Deliberately no criteria: see the module docstring. `task_description` and
    `artifact_fields` are what the student is asked to do, which is not the same
    thing as what they will be judged against.
    """
    provider = get_provider()
    phases = []
    for meta in prompts.list_phases():
        doc = prompts.load_phase(meta["phase"])
        phases.append(
            {
                "phase": meta["phase"],
                "label": doc.get("label") or meta["label"],
                "order": meta["order"],
                "task_description": doc.get("task_description", ""),
                "artifact_fields": doc.get("artifact_fields") or [],
            }
        )
    # The page disables Run honestly rather than failing on click, and a verdict can be
    # traced back to the toolchain that produced it.
    try:
        executor = get_executor()
        executor_info = {
            "available": True,
            "name": executor.name,
            "isolation": executor.isolation,
            "toolchain": describe_toolchain(executor),
            "error": "",
        }
    except ExecutorError as exc:
        executor_info = {
            "available": False, "name": "", "isolation": "", "toolchain": "", "error": str(exc)
        }

    return {
        "phases": phases,
        "problems": prompts.list_problems(),
        "has_api_key": provider.has_api_key(),
        "executor": executor_info,
    }


def problem(slug: str) -> dict:
    """One problem as the student reads it: the statement, the examples they were
    given, and the starter code to begin from. Everything else in the file -- the
    hidden test cases above all -- is authoring metadata.

    The dict below is built key by key rather than by copying `doc`, which is what
    makes the omission structural: a field added to the problem schema tomorrow does
    not reach a student until someone deliberately adds a line here.
    """
    doc = prompts.load_problem(slug)
    return {
        "problem": {
            "slug": doc.get("slug", slug),
            "title": doc.get("title", slug),
            "statement": doc.get("statement", ""),
            "starter_code": doc.get("starter_code", ""),
            "public_test_cases": doc.get("public_test_cases") or [],
        }
    }


def run(body: dict) -> dict:
    """Compile and check against the public cases only. No judge, no nudge, no attempt.

    The Run button. It is deliberately not a submission: a student should be able to
    press it as often as they like, and nothing about it is recorded or costs a model
    call. `scope="public"` is fixed here rather than taken from the body, so no request
    can ask this endpoint to run the hidden cases and read back the count.
    """
    prob = prompts.load_problem(body["problem_id"])
    return grading.grade(prob, body.get("code") or "", scope="public")


def _context(body: dict) -> tuple[dict, dict, list[dict]]:
    """Phase, problem and criteria for a student request — always from disk."""
    phase = prompts.load_phase(body["phase_id"])
    prob = prompts.load_problem(body["problem_id"])
    criteria = prompts.load_criteria(phase["phase"])["criteria"]
    return phase, prob, criteria


def submit(body: dict) -> dict:
    """Judge one submission, then nudge on it if a gate failed.

    Returns the verdicts with each criterion's text and gate attached, which is the
    first and only point at which the rubric reaches the student. `passed` is decided
    here rather than in the page: a missing verdict is not a pass, whatever its gate --
    the judge failing to rule on a criterion is a broken contract, not a met one.
    """
    phase, prob, criteria = _context(body)

    # Every other gate, named or absent, falls through to the judged path below unchanged.
    if phase.get("gate") == "tests":
        return _submit_tests(phase, prob, criteria, body)

    artifact = body.get("artifact") or {}
    attempt = int(body.get("attempt", 1))
    prior = body.get("prior_artifacts") or []

    result = judging.judge(phase, prob, artifact, criteria, attempt, prior)

    by_id = {c["id"]: c for c in criteria}
    verdicts = []
    for v in result["verdicts"]:
        c = by_id.get(v["criterion_id"], {})
        verdicts.append(
            {
                "criterion_id": v["criterion_id"],
                "criterion_text": c.get("text", ""),
                "gate": c.get("gate", prompts.DEFAULT_GATE),
                "verdict": v["verdict"],
                "evidence": v.get("evidence", ""),
                # The audit is shown to the student because a quote that is not in
                # their artifact is a judge that asserted rather than read, and they
                # are entitled to see that rather than accept the verdict on trust.
                "evidence_found": v.get("evidence_found", True),
            }
        )

    blocking = [
        v["criterion_id"] for v in verdicts
        if v["verdict"] == "FAIL" and v["gate"] != "advisory"
    ]
    advisory_unmet = [
        v["criterion_id"] for v in verdicts
        if v["verdict"] == "FAIL" and v["gate"] == "advisory"
    ]
    missing = result["missing_ids"]

    out = {
        "verdicts": verdicts,
        "blocking": blocking,
        "advisory_unmet": advisory_unmet,
        "missing_ids": missing,
        "passed": not blocking and not missing,
        "nudge": None,
        "nudge_error": None,
    }

    if blocking:
        # In the same call, so no page can show a failure without its guidance. A
        # nudge that fails is reported beside verdicts that stand on their own —
        # losing the nudge must not cost the student the judging they waited for.
        try:
            n = nudging.nudge(
                phase, prob, artifact, criteria, result["verdicts"],
                attempt, prior, body.get("history") or [],
            )
            out["nudge"] = {
                "summary": n["summary"],
                "focus_id": n["focus_id"],
                "focus_text": n["focus_text"],
                "reason": n["reason"],
                "nudge": n["nudge"],
                "failing": n["failing"],
            }
        except nudging.JudgeError as exc:
            out["nudge_error"] = str(exc)

    return out


def _submit_tests(phase: dict, prob: dict, criteria: list[dict], body: dict) -> dict:
    """A tests-gated submission: graded first, judged only if it already works.

    The judge is not called on failing code, for two reasons. It spends a call to
    review something the student is about to change anyway; and skipping it means the
    advisory review always reads a working program, so it can be written to comment on
    conformance rather than on correctness.

    `blocking` stays empty because a failing test is not a criterion. Nothing downstream
    should mistake a wrong answer for a rubric failure.
    """
    artifact = body.get("artifact") or {}
    code = body.get("code") or artifact.get("code") or ""
    attempt = int(body.get("attempt", 1))
    prior = body.get("prior_artifacts") or []

    try:
        test_run = grading.grade(prob, code, scope="all")
    except ExecutorError as exc:
        raise judging.JudgeError(str(exc)) from None

    out = {
        "test_run": test_run,
        "verdicts": [],
        "blocking": [],
        "advisory_unmet": [],
        "missing_ids": [],
        "passed": False,
        "nudge": None,
        "nudge_error": None,
    }

    if not test_run["passed"]:
        try:
            out["nudge"] = nudging.nudge_code(phase, prob, code, test_run, attempt, prior)
        except nudging.JudgeError as exc:
            # Losing the nudge must not cost the student the results they waited for.
            out["nudge_error"] = str(exc)
        return out

    out["passed"] = True

    # Advisory review, on code already known to work. A failure here is reported and
    # never bars: `passed` is already true and stays true.
    try:
        result = judging.judge(phase, prob, artifact or {"code": code}, criteria, attempt, prior)
    except judging.JudgeError as exc:
        out["nudge_error"] = str(exc)
        return out

    by_id = {c["id"]: c for c in criteria}
    for v in result["verdicts"]:
        c = by_id.get(v["criterion_id"], {})
        out["verdicts"].append(
            {
                "criterion_id": v["criterion_id"],
                "criterion_text": c.get("text", ""),
                "gate": c.get("gate", prompts.DEFAULT_GATE),
                "verdict": v["verdict"],
                "evidence": v.get("evidence", ""),
                "evidence_found": v.get("evidence_found", True),
            }
        )
    out["advisory_unmet"] = [v["criterion_id"] for v in out["verdicts"] if v["verdict"] == "FAIL"]
    out["missing_ids"] = result["missing_ids"]
    return out


def hint(body: dict) -> dict:
    """One hint, before or after any submission.

    Returns only what the student is meant to read. `criterion_text` comes back with
    it because a hint that points somewhere without saying where is not a hint — but
    it is always an advisory criterion, which `hint()` guarantees and this cannot widen.
    """
    phase, prob, criteria = _context(body)
    h = hinting.hint(
        phase,
        prob,
        body.get("artifact") or {},
        criteria,
        int(body.get("attempt", 1)),
        body.get("prior_artifacts") or [],
        body.get("history") or [],
    )
    return {
        "criterion_id": h["criterion_id"],
        "criterion_text": h["criterion_text"],
        "diagnosis": h["diagnosis"],
        "hint": h["hint"],
    }
