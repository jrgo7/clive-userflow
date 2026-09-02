"""The persona and the simulation loop. No network.

The property worth pinning hardest is what a persona is *not* shown. A simulated student
handed the rubric writes to the rubric, and a run against it measures nothing — so these
assert the criteria never reach the student prompt on a first attempt, and that what does
reach it on a retry is only what a real student would have been looking at.
"""

from __future__ import annotations

import types

import pytest

from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import persona as writing
from clive import prompts
from clive import simulate

PHASE = "problem_definition"


def all_criteria() -> list[dict]:
    return [c for m in prompts.list_phases() for c in prompts.load_criteria(m["phase"])["criteria"]]


class Stub:
    """One stub for all four schemas. `fail` names the criteria to mark FAIL."""

    name, api_key_env, default_model = "stub", "STUB_KEY", "stub-1"
    model_choices = ["stub-1"]

    def __init__(self, fail: set[str] | None = None, fail_first_only: bool = False):
        self.fail = fail or set()
        self.fail_first_only = fail_first_only
        self.seen: list[tuple[str, str]] = []
        self.judged = 0

    def has_api_key(self) -> bool:
        return True

    @staticmethod
    def phase_of(user: str) -> str:
        best, hits = PHASE, -1
        for m in prompts.list_phases():
            ids = [c["id"] for c in prompts.load_criteria(m["phase"])["criteria"]]
            n = sum(1 for i in ids if i in user)
            if n > hits:
                best, hits = m["phase"], n
        return best

    def judge_json(self, system, user, model, max_output_tokens, effort, schema):
        name = schema.__name__
        self.seen.append((name, user))
        if name == "StudentArtifact":
            parsed = schema(**{k: f"text for {k}" for k in schema.model_fields})
        elif name == "JudgeResult":
            self.judged += 1
            bad = self.fail if not (self.fail_first_only and self.judged > 1) else set()
            ids = [c["id"] for c in prompts.load_criteria(self.phase_of(user))["criteria"]]
            parsed = schema(verdicts=[
                {"criterion_id": i, "verdict": "FAIL" if i in bad else "PASS",
                 "evidence": "text for inputs", "confidence": "high"} for i in ids])
        elif name == "Nudge":
            first = next(iter(sorted(self.fail))) if self.fail else "novel_wording"
            parsed = schema(summary="Some things are open.", focus_id=first,
                            reason="upstream", nudge="What kind of number?")
        elif name == "Hint":
            # Always an advisory criterion: that is `hint()`'s own guarantee, and this
            # stub must not be the thing that breaks it.
            advisory = [c for c in prompts.load_criteria(self.phase_of(user))["criteria"]
                        if c["gate"] == "advisory"]
            parsed = schema(criterion_id=advisory[0]["id"],
                            diagnosis="You look unsure where to start.",
                            hint="Try reading the last line of the statement again.")
        else:
            raise AssertionError(f"unexpected schema {name}")
        return types.SimpleNamespace(model="stub-1", input_tokens=100, output_tokens=50, parsed=parsed)


@pytest.fixture
def stub(monkeypatch):
    def install(**kw):
        p = Stub(**kw)
        # hinting included: a module left unpatched here does not fail loudly, it
        # reaches the real provider and makes a billable network call from the suite.
        for mod in (hinting, judging, nudging, writing):
            monkeypatch.setattr(mod, "get_provider", lambda *a, **k: p)
        return p
    return install


# ------------------------------------------------------------------- personas


def test_personas_load_and_validate():
    doc = prompts.load_personas()
    assert doc["personas"], "no personas defined"
    for p in doc["personas"]:
        assert p["id"] and p["name"] and p["behaviour"].strip()


def test_personas_have_unique_ids():
    ids = [p["id"] for p in prompts.load_personas()["personas"]]
    assert len(ids) == len(set(ids))


def test_find_persona_names_the_alternatives():
    with pytest.raises(prompts.ContentError) as e:
        prompts.find_persona(prompts.load_personas(), "no_such_persona")
    assert "diligent" in str(e.value)


def test_artifact_schema_matches_the_phase_fields():
    phase = prompts.load_phase(PHASE)
    model = writing.artifact_schema(phase["artifact_fields"])
    assert set(model.model_fields) == {f["id"] for f in phase["artifact_fields"]}


def test_artifact_schema_refuses_a_phase_with_no_fields():
    with pytest.raises(writing.JudgeError):
        writing.artifact_schema([])


# ------------------------------------------- what the student is and is not shown


def test_first_attempt_prompt_contains_no_rubric():
    doc = prompts.load_personas()
    p = prompts.find_persona(doc, "diligent")
    text = prompts.render_persona_prompt(
        doc, p, prompts.load_phase(PHASE), prompts.load_problem("grade_average"))
    for c in all_criteria():
        assert c["id"] not in text
        assert c["text"] not in text


def test_retry_prompt_shows_only_what_a_student_would_have_seen():
    doc = prompts.load_personas()
    p = prompts.find_persona(doc, "diligent")
    feedback = {
        "failed": [{"text": "Types must be specific and concrete.", "evidence": "a list"}],
        "nudge": {"summary": "One thing is open.", "nudge": "A list of what?"},
        "previous": [{"label": "Inputs", "value": "a list"}],
    }
    text = prompts.render_persona_prompt(
        doc, p, prompts.load_phase(PHASE), prompts.load_problem("grade_average"),
        attempt=2, feedback=feedback)
    assert "Types must be specific and concrete." in text   # the verdict they were shown
    assert "A list of what?" in text                        # the nudge they were shown
    # Still no criterion ids, and no criterion they were never judged against.
    for c in all_criteria():
        assert c["id"] not in text
    assert "restates_ambiguity" not in text


def test_persona_prompt_carries_earlier_work():
    doc = prompts.load_personas()
    p = prompts.find_persona(doc, "diligent")
    text = prompts.render_persona_prompt(
        doc, p, prompts.load_phase("case_design"), prompts.load_problem("grade_average"),
        prior_artifacts=[{"label": "Problem", "fields": [{"label": "Summary", "value": "my summary"}]}])
    assert "my summary" in text


# ------------------------------------------------------------------ the loop


def events(stub_provider, **kw):
    kw.setdefault("max_attempts", 2)
    kw.setdefault("phase_ids", [PHASE])
    return list(simulate.run("minimalist", "grade_average", **kw))


def test_clean_run_emits_the_expected_shape(stub):
    stub()
    kinds = [e["type"] for e in events(stub)]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert kinds.count("artifact") == 1        # passed first time
    assert "nudge" not in kinds


def test_a_blocked_attempt_is_nudged_then_retried(stub):
    stub(fail={"concrete_types"}, fail_first_only=True)
    evs = events(stub)
    kinds = [e["type"] for e in evs]
    assert kinds.count("artifact") == 2
    assert kinds.count("nudge") == 1
    assert [e for e in evs if e["type"] == "verdicts"][-1]["passed"] is True
    assert evs[-1]["completed"] is True


def test_advisory_failure_alone_does_not_block(stub):
    stub(fail={"output_form_exact"})           # advisory
    evs = events(stub)
    v = [e for e in evs if e["type"] == "verdicts"][0]
    assert v["passed"] is True
    assert v["advisory_unmet"] == ["output_form_exact"]
    assert not [e for e in evs if e["type"] == "nudge"]


def test_an_unpassed_phase_stops_the_run(stub):
    """The gating rule, not a shortcut: a real student never reaches the next phase."""
    stub(fail={"novel_wording"})
    evs = list(simulate.run("minimalist", "grade_average", max_attempts=2))
    assert len([e for e in evs if e["type"] == "phase_start"]) == 1
    assert evs[-1]["type"] == "done" and evs[-1]["completed"] is False


def test_max_attempts_is_honoured_and_capped(stub):
    p = stub(fail={"novel_wording"})
    events(stub, max_attempts=3)
    assert p.judged == 3
    p2 = stub(fail={"novel_wording"})
    events(stub, max_attempts=99)
    assert p2.judged == simulate.MAX_ATTEMPTS_CAP


def test_usage_is_accumulated(stub):
    stub(fail={"concrete_types"}, fail_first_only=True)
    done = events(stub)[-1]
    # attempt 1: write + judge + nudge, attempt 2: write + judge
    assert done["usage"]["calls"] == 5
    assert done["usage"]["input_tokens"] == 500


def test_run_never_shows_the_rubric_to_the_student(stub):
    """The whole point, asserted against a real run rather than one rendered prompt."""
    p = stub(fail={"concrete_types"}, fail_first_only=True)
    events(stub)
    student_prompts = [u for (n, u) in p.seen if n == "StudentArtifact"]
    assert student_prompts
    for text in student_prompts:
        for c in all_criteria():
            assert c["id"] not in text, f"{c['id']} reached the student"


def test_unknown_persona_raises_for_the_server_to_report():
    """`run` raises; the SSE handler turns it into an error event, because a stream has
    already sent its status line and cannot answer with a 400."""
    with pytest.raises(prompts.ContentError):
        list(simulate.run("nope", "grade_average"))


# ------------------------------------------------------------- asking for help


def test_every_persona_declares_a_valid_help_seeking_mode():
    for p in prompts.load_personas()["personas"]:
        assert p["help_seeking"] in prompts.HELP_SEEKING


def test_bad_help_seeking_is_rejected(monkeypatch):
    doc = prompts.load_personas()
    doc["personas"][0]["help_seeking"] = "whenever"
    monkeypatch.setattr(prompts, "read_yaml", lambda path: doc)
    with pytest.raises(prompts.ContentError) as e:
        prompts.load_personas()
    assert "help_seeking" in str(e.value)


@pytest.mark.parametrize("mode,attempt,expected", [
    ("never", 1, False), ("never", 3, False),
    ("when_stuck", 1, False), ("when_stuck", 2, True),
    ("eager", 1, True), ("eager", 2, True),
])
def test_who_presses_the_help_button_and_when(mode, attempt, expected):
    assert simulate._asks_for_help({"help_seeking": mode}, attempt) is expected


def test_an_eager_persona_asks_before_writing_anything(stub):
    p = stub()
    evs = list(simulate.run("utter_beginner", "grade_average",
                            max_attempts=1, phase_ids=[PHASE]))
    kinds = [e["type"] for e in evs]
    assert kinds.index("hint") < kinds.index("artifact"), "help must come before the writing"
    # The hint ran against an empty artifact: the staring-at-a-blank-form case.
    hint_prompt = next(u for (n, u) in p.seen if n == "Hint")
    assert "(not provided)" in hint_prompt


def test_a_never_persona_costs_no_hint_call(stub):
    p = stub()
    evs = list(simulate.run("minimalist", "grade_average", max_attempts=1, phase_ids=[PHASE]))
    assert not [e for e in evs if e["type"] == "hint"]
    assert not [n for (n, _) in p.seen if n == "Hint"]


def test_the_hints_prose_reaches_the_student_but_not_its_criterion(stub):
    """A persona that could read the rule would satisfy it, and the run would report
    the hint as more use than it is."""
    p = stub()
    list(simulate.run("utter_beginner", "grade_average", max_attempts=1, phase_ids=[PHASE]))
    written = [u for (n, u) in p.seen if n == "StudentArtifact"]
    assert any("HELP YOU ASKED FOR" in u for u in written)
    assert any("reading the last line of the statement" in u for u in written)
    for text in written:
        for c in all_criteria():
            assert c["id"] not in text
