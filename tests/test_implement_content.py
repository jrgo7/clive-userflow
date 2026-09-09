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


def test_problems_with_starter_code_start_from_a_compilable_skeleton():
    for slug in ("count_vowels", "crowley_path"):
        starter = prompts.load_problem(slug)["starter_code"]
        assert "#include <stdio.h>" in starter
        assert "int main(void)" in starter
