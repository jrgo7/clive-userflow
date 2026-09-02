"""The student-facing API: the same engine as the Studio, shaped for the person
being taught rather than the person authoring the rubric.

The Studio hands the browser everything, because an author needs to see everything.
A student must not have all of it, and the difference is not cosmetic -- so it lives
here in the server rather than as restraint in the page:

  The rubric is never sent before it has been ruled on. `boot` returns phases without
  their criteria; a criterion's text reaches the browser only attached to a verdict on
  it, in `submit`. Shipping the whole rubric and hiding it in the page would put the
  checklist one devtools panel away from the student it is meant to make think.

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

from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import prompts
from clive.providers import get_provider

__all__ = ["boot", "problem", "submit", "hint"]


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
    return {
        "phases": phases,
        "problems": prompts.list_problems(),
        "has_api_key": provider.has_api_key(),
    }


def problem(slug: str) -> dict:
    """One problem as the student reads it: the statement and the examples they were
    given. Everything else in the file is authoring metadata."""
    doc = prompts.load_problem(slug)
    return {
        "problem": {
            "slug": doc.get("slug", slug),
            "title": doc.get("title", slug),
            "statement": doc.get("statement", ""),
            "public_test_cases": doc.get("public_test_cases") or [],
        }
    }


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
