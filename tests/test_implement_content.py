"""The Implement phase's authored content, and the one rule it must never break.

`student.submit` treats a tests-gated phase as passed the moment every case passes.
A gating criterion in criteria/implement.yaml would let the judge block code that
demonstrably works, which the design rules out -- so it is pinned here rather than
left as a convention someone edits away.
"""

from __future__ import annotations

from clive import prompts


def test_implement_is_the_fourth_phase():
    phases = prompts.list_phases()
    assert [p["phase"] for p in phases][-1] == "implement"
    assert phases[-1]["order"] == 4


def test_implement_is_gated_by_tests():
    assert prompts.load_phase("implement")["gate"] == "tests"


def test_implement_submits_one_code_field():
    fields = prompts.load_phase("implement")["artifact_fields"]
    assert len(fields) == 1
    assert fields[0]["id"] == "code"
    assert fields[0]["kind"] == "code"
    assert fields[0]["language"] == "c"


def test_every_implement_criterion_is_advisory():
    criteria = prompts.load_criteria("implement")["criteria"]
    assert criteria, "the phase needs criteria for the advisory review to say anything"
    offenders = [c["id"] for c in criteria if c["gate"] != "advisory"]
    assert not offenders, (
        f"{offenders} would let the judge block code that passes every test. "
        "Implement is gated by the compiler; its criteria advise and never bar."
    )


def test_the_template_renders_with_a_code_artifact():
    phase = prompts.load_phase("implement")
    rendered = prompts.render_user_prompt(
        phase,
        prompts.load_problem("count_vowels"),
        {"code": "int main(void) { return 0; }"},
        prompts.load_criteria("implement")["criteria"],
        attempt=1,
        prior_artifacts=[{"label": "Design", "fields": [{"label": "Steps", "value": "1. Read"}]}],
    )
    assert "int main(void) { return 0; }" in rendered
    assert "1. Read" in rendered


def test_problem_for_template_strips_hidden_cases_but_keeps_everything_else():
    problem = {
        "statement": "s", "public_test_cases": [{"input": "a", "output": "b"}],
        "hidden_test_cases": [{"input": "x", "output": "y"}], "starter_code": "c",
    }
    view = prompts._problem_for_template(problem)
    assert "hidden_test_cases" not in view
    assert view["statement"] == "s"
    assert view["starter_code"] == "c"
    assert view["public_test_cases"] == [{"input": "a", "output": "b"}]
    # Not mutated: `problem` may be the caller's own loaded dict.
    assert problem["hidden_test_cases"] == [{"input": "x", "output": "y"}]


def test_the_judge_prompt_never_leaks_a_hidden_test_case(tmp_path, monkeypatch):
    """The one link in the hidden-case leak guard that used to rely on "no template
    happens to reference hidden_test_cases" rather than the data simply not being
    there -- see `prompts._problem_for_template`. `render_user_prompt` receives the
    FULL `load_problem()` dict (hidden cases included), exactly as `judging.judge()`
    hands it on for a tests-gated submission's advisory review
    (`studio/student.py::_submit_tests`) -- so this must hold structurally, not
    merely because today's templates happen not to mention the field.
    """
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("leaky", {
        "statement": "Count something.\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET_HIDDEN_INPUT", "output": "SECRET_HIDDEN_OUTPUT"}],
    })
    problem = prompts.load_problem("leaky")
    assert problem["hidden_test_cases"]  # sanity: the fixture actually has one

    rendered = prompts.render_user_prompt(
        prompts.load_phase("implement"),
        problem,
        {"code": "int main(void) { return 0; }"},
        prompts.load_criteria("implement")["criteria"],
        attempt=1,
    )
    assert "SECRET_HIDDEN_INPUT" not in rendered
    assert "SECRET_HIDDEN_OUTPUT" not in rendered


def test_the_code_nudge_prompt_never_leaks_a_hidden_test_case(tmp_path, monkeypatch):
    """Same guard as above, for `render_nudge_code_prompt` -- the code-nudge template
    also receives the full problem dict, not just the caller-selected `failures`."""
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("leaky", {
        "statement": "Count something.\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET_HIDDEN_INPUT", "output": "SECRET_HIDDEN_OUTPUT"}],
    })
    problem = prompts.load_problem("leaky")

    rendered = prompts.render_nudge_code_prompt(
        prompts.load_nudge_code(),
        prompts.load_phase("implement"),
        problem,
        "int main(void) { return 1; }",
        failures=[{"id": "0", "input": "a", "expected": "1", "actual": "2", "status": "ok"}],
        hidden_failed=1,
    )
    assert "SECRET_HIDDEN_INPUT" not in rendered
    assert "SECRET_HIDDEN_OUTPUT" not in rendered


def test_problems_with_starter_code_start_from_a_compilable_skeleton():
    for slug in ("count_vowels", "crowley_path"):
        starter = prompts.load_problem(slug)["starter_code"]
        assert "#include <stdio.h>" in starter
        assert "int main(void)" in starter
