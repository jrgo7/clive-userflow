"""The student API's boundaries — what a student may see, and when. No network.

These are not tests of the judge or the nudge; those are covered by their own guards.
They pin the one thing the student route exists to enforce, which no amount of care in
the page can guarantee on its own: the rubric does not reach the browser until it has
been ruled on, and nothing about the machinery reaches it at all.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import prompts
from clive.studio import student

PHASE = "problem_definition"
STATIC = Path(__file__).resolve().parents[1] / "src" / "clive" / "studio" / "static"

ARTIFACT = {
    "summary": "Get the mean of all the grades of each student.",
    "inputs": "Input is a list.",
    "outputs": "Output is a single float/double",
}


def all_criteria() -> list[dict]:
    return [c for m in prompts.list_phases() for c in prompts.load_criteria(m["phase"])["criteria"]]


class StubProvider:
    """Answers whatever schema it is handed, so one stub serves judge, nudge and hint."""

    name, api_key_env, default_model = "stub", "STUB_KEY", "stub-1"
    model_choices = ["stub-1"]

    def __init__(self, plan: dict[str, str]):
        self.plan = plan

    def has_api_key(self) -> bool:
        return True

    def judge_json(self, system, user, model, max_output_tokens, effort, schema):
        name = schema.__name__
        if name == "JudgeResult":
            parsed = schema(verdicts=[
                {"criterion_id": cid, "verdict": v, "evidence": "Input is a list.", "confidence": "high"}
                for cid, v in self.plan.items()
            ])
        elif name == "Nudge":
            first = next(c for c, v in self.plan.items() if v == "FAIL")
            parsed = schema(summary="Two things are open.", focus_id=first,
                            reason="It is upstream.", nudge="A list of what?")
        else:
            parsed = schema(criterion_id="output_form_exact", diagnosis="d", hint="h")
        return types.SimpleNamespace(model="stub-1", input_tokens=1, output_tokens=1, parsed=parsed)


@pytest.fixture
def stub(monkeypatch):
    def install(plan):
        p = StubProvider(plan)
        for mod in (judging, hinting, nudging):
            monkeypatch.setattr(mod, "get_provider", lambda *a, **k: p)
        return p
    return install


ALL_FAIL_TWO = {
    "novel_wording": "PASS", "concrete_types": "FAIL", "constraints_noted": "FAIL",
    "input_order_stated": "FAIL", "output_form_exact": "FAIL", "restates_ambiguity": "FAIL",
}
ALL_PASS = {k: "PASS" for k in ALL_FAIL_TWO}


def submit(plan, stub, **over):
    stub(plan)
    body = {"phase_id": PHASE, "problem_id": "grade_average", "artifact": ARTIFACT, "attempt": 1}
    body.update(over)
    return student.submit(body)


# ------------------------------------------------------------------ boot / problem


def test_boot_carries_no_criteria():
    """The rubric is not sent before it has been ruled on."""
    boot = student.boot()
    assert boot["phases"], "no phases configured"
    for p in boot["phases"]:
        assert "criteria" not in p
    blob = json.dumps(boot)
    for c in all_criteria():
        assert c["id"] not in blob
        assert c["text"] not in blob


def test_boot_carries_what_the_student_is_asked_to_do():
    for p in student.boot()["phases"]:
        assert "task_description" in p and "artifact_fields" in p


def test_problem_exposes_only_student_facing_keys():
    prob = student.problem("grade_average")["problem"]
    assert set(prob) == {"slug", "title", "statement", "public_test_cases"}


# ------------------------------------------------------------------------ submit


def test_advisory_failure_does_not_block(stub):
    r = submit(ALL_FAIL_TWO, stub)
    assert r["blocking"] == ["concrete_types", "constraints_noted"]
    assert len(r["advisory_unmet"]) == 3
    assert r["passed"] is False


def test_verdicts_carry_text_and_gate(stub):
    """This is the only point at which the rubric reaches the student."""
    r = submit(ALL_FAIL_TWO, stub)
    assert all(v["criterion_text"] for v in r["verdicts"])
    assert {v["gate"] for v in r["verdicts"]} == {"gating", "advisory"}


def test_nudge_arrives_with_the_failure(stub):
    r = submit(ALL_FAIL_TWO, stub)
    assert [f["id"] for f in r["nudge"]["failing"]] == ["concrete_types", "constraints_noted"]
    assert r["nudge"]["focus_id"] == "concrete_types"


def test_no_nudge_when_nothing_blocks(stub):
    r = submit(ALL_PASS, stub)
    assert r["passed"] is True
    assert r["nudge"] is None and r["nudge_error"] is None


def test_missing_verdict_is_not_a_pass(stub):
    """A criterion the judge skipped blocks, but there is nothing to nudge about."""
    plan = dict(ALL_PASS)
    plan.pop("restates_ambiguity")
    r = submit(plan, stub)
    assert r["passed"] is False
    assert r["missing_ids"] == ["restates_ambiguity"]
    assert r["nudge"] is None


def test_submit_leaks_no_machinery(stub):
    blob = json.dumps(submit(ALL_FAIL_TWO, stub))
    assert "PROBLEM STATEMENT" not in blob   # the rendered prompt
    assert "stub-1" not in blob              # the model id
    assert "input_tokens" not in blob        # token counts


def test_submit_leaks_no_unjudged_criterion(stub):
    """Only criteria that were ruled on may appear — a phase's rubric must not
    arrive whole on the back of one submission."""
    r = submit(ALL_FAIL_TWO, stub)
    ruled = {v["criterion_id"] for v in r["verdicts"]}
    blob = json.dumps(r)
    for c in all_criteria():
        if c["id"] not in ruled:
            assert c["id"] not in blob and c["text"] not in blob


# -------------------------------------------------------------------------- hint


def test_hint_returns_only_student_facing_fields(stub):
    stub(ALL_FAIL_TWO)
    h = student.hint({"phase_id": PHASE, "problem_id": "grade_average", "artifact": ARTIFACT})
    assert set(h) == {"criterion_id", "criterion_text", "diagnosis", "hint"}


def test_hint_can_only_ever_point_at_advisory_depth(stub):
    stub(ALL_FAIL_TWO)
    h = student.hint({"phase_id": PHASE, "problem_id": "grade_average", "artifact": ARTIFACT})
    gate = {c["id"]: c["gate"] for c in prompts.load_criteria(PHASE)["criteria"]}
    assert gate[h["criterion_id"]] == "advisory"


# -------------------------------------------------------------------- the page


def test_served_page_ships_no_rubric():
    """Not even in a comment: the file is served to the student, so a criterion id
    written into it is a piece of the rubric one view-source away."""
    page = (STATIC / "student.html").read_text(encoding="utf-8")
    for c in all_criteria():
        assert c["id"] not in page, f"{c['id']} appears in student.html"
        assert c["text"] not in page
