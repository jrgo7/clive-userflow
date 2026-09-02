"""A whole session, driven by a persona: write, judge, nudge, revise, advance.

The loop a student walks, with a model in the student's chair. Everything else is the
real thing — the same `judge`, the same `nudge`, the same gating rule and the same saved
criteria the Studio and the student view use. Only the student is synthetic.

This is an author's instrument, not a student feature. What it is for is answering
questions about a rubric that are otherwise expensive to answer: does a thin answer get
blocked for the reason I intended, does the nudge point somewhere that helps, does a
competent answer actually get through, and does a phase take two attempts or six.

`run` is a generator of plain dicts and performs no I/O of its own beyond the model calls
and reading the saved files. That is deliberate: the server streams the events to a
browser, and a test drives the same generator with a stubbed provider and asserts on the
sequence. Neither knows about the other.
"""

from __future__ import annotations

from typing import Iterator

from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import persona as writing
from clive import prompts
from clive.providers.base import JudgeError

__all__ = ["MAX_ATTEMPTS_CAP", "run"]

#: An upper bound on attempts per phase, whatever the caller asks for. A persona that
#: cannot pass will not pass on the twentieth try either, and each attempt is three model
#: calls — this is the difference between a slow run and an expensive accident.
MAX_ATTEMPTS_CAP = 8


def _asks_for_help(persona: dict, attempt: int) -> bool:
    """Whether this character presses the help button before this attempt.

    Declared on the persona rather than decided by a model: asking "would you like a
    hint?" would be a whole extra call to answer a question the character already
    answers. `when_stuck` means after a failure, so it never fires on attempt 1.
    """
    mode = persona.get("help_seeking", "never")
    return mode == "eager" or (mode == "when_stuck" and attempt > 1)


def _prior(phases: list[dict], done: dict[str, dict]) -> list[dict]:
    """Earlier phases' artifacts, in phase order, shaped for both templates.

    The persona reads these as its own earlier work; the judge reads them as context for
    a criterion that refers back. Same structure for both, which is why it is built once.
    """
    out = []
    for p in phases:
        art = done.get(p["phase"])
        if not art:
            continue
        fields = [
            {"label": f.get("label") or f["id"], "value": art[f["id"]]}
            for f in p.get("artifact_fields") or []
            if str(art.get(f["id"], "")).strip()
        ]
        if fields:
            out.append({"label": p.get("label") or p["phase"], "fields": fields})
    return out


def run(
    persona_id: str,
    problem_id: str,
    max_attempts: int = 3,
    phase_ids: list[str] | None = None,
) -> Iterator[dict]:
    """Walk one persona through every phase, yielding an event per step.

    Events all carry a `type`. The caller renders them in order and needs no other state:
    every event that belongs to a phase names it, so a dropped connection loses the tail
    of a run rather than corrupting what was already shown.

    A phase that is never passed stops the run. That is the gating rule, not a shortcut —
    a student who cannot get through Problem never sees Cases, and a simulation that
    marched on regardless would be testing a system nobody uses.
    """
    attempts_allowed = max(1, min(int(max_attempts or 1), MAX_ATTEMPTS_CAP))

    persona_doc = prompts.load_personas()
    persona = prompts.find_persona(persona_doc, persona_id)
    problem = prompts.load_problem(problem_id)

    metas = prompts.list_phases()
    if phase_ids:
        wanted = set(phase_ids)
        metas = [m for m in metas if m["phase"] in wanted]
    phases = [prompts.load_phase(m["phase"]) for m in metas]
    if not phases:
        yield {"type": "error", "message": "There are no phases to run.", "fatal": True}
        return

    yield {
        "type": "start",
        "persona": {"id": persona["id"], "name": persona["name"], "blurb": persona.get("blurb", "")},
        "problem": {"slug": problem.get("slug", problem_id), "title": problem.get("title", problem_id)},
        "phases": [{"phase": p["phase"], "label": p.get("label") or p["phase"]} for p in phases],
        "max_attempts": attempts_allowed,
    }

    done: dict[str, dict] = {}
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    summary: list[dict] = []

    def spend(usage: dict) -> None:
        totals["calls"] += 1
        totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        totals["output_tokens"] += int(usage.get("output_tokens") or 0)

    for index, phase in enumerate(phases):
        pid = phase["phase"]
        label = phase.get("label") or pid
        criteria = prompts.load_criteria(pid)["criteria"]
        if not criteria:
            yield {"type": "error", "fatal": True,
                   "message": f"{label} has no criteria, so there is nothing to judge against."}
            return

        by_id = {c["id"]: c for c in criteria}
        prior = _prior(phases[:index], done)
        feedback: dict | None = None
        passed = False
        attempt = 1

        yield {"type": "phase_start", "phase": pid, "label": label,
               "index": index, "total": len(phases)}

        last_artifact: dict = {}

        while attempt <= attempts_allowed:
            # The help button, pressed before writing. `eager` asks straight away, which
            # is the empty-form case `hint()` was built for; `when_stuck` waits until a
            # phase has already been failed. Only the hint's prose is handed on — the
            # criterion it points at stays out, or a persona could satisfy a rule it was
            # never meant to see and the run would flatter the hint.
            help_text = None
            if _asks_for_help(persona, attempt):
                yield {"type": "working", "phase": pid, "attempt": attempt, "what": "asking"}
                try:
                    h = hinting.hint(phase, problem, last_artifact, criteria, attempt, prior)
                    spend(h["usage"])
                    help_text = {"diagnosis": h["diagnosis"], "hint": h["hint"]}
                    yield {"type": "hint", "phase": pid, "attempt": attempt,
                           "criterion_id": h["criterion_id"], "criterion_text": h["criterion_text"],
                           **help_text}
                except JudgeError as exc:
                    # A phase with no advisory criteria has nothing to hint at. Not fatal:
                    # the student simply gets on with it, which is worth seeing.
                    yield {"type": "error", "phase": pid, "attempt": attempt, "fatal": False,
                           "message": f"No help available: {exc}"}

            yield {"type": "working", "phase": pid, "attempt": attempt, "what": "writing"}
            try:
                wrote = writing.write(persona, phase, problem, attempt, prior, feedback,
                                      persona_doc, help_text)
            except JudgeError as exc:
                yield {"type": "error", "phase": pid, "attempt": attempt, "fatal": True,
                       "message": f"The student could not write: {exc}"}
                return
            spend(wrote["usage"])
            artifact = wrote["artifact"]
            last_artifact = artifact
            yield {
                "type": "artifact", "phase": pid, "attempt": attempt,
                "fields": [
                    {"id": f["id"], "label": f.get("label") or f["id"], "value": artifact.get(f["id"], "")}
                    for f in phase.get("artifact_fields") or []
                ],
            }

            yield {"type": "working", "phase": pid, "attempt": attempt, "what": "judging"}
            try:
                result = judging.judge(phase, problem, artifact, criteria, attempt, prior)
            except JudgeError as exc:
                yield {"type": "error", "phase": pid, "attempt": attempt, "fatal": True,
                       "message": f"The judge failed: {exc}"}
                return
            spend(result["usage"])

            verdicts = [
                {
                    "criterion_id": v["criterion_id"],
                    "criterion_text": by_id.get(v["criterion_id"], {}).get("text", ""),
                    "gate": by_id.get(v["criterion_id"], {}).get("gate", prompts.DEFAULT_GATE),
                    "verdict": v["verdict"],
                    "evidence": v.get("evidence", ""),
                    "evidence_found": v.get("evidence_found", True),
                }
                for v in result["verdicts"]
            ]
            blocking = [v["criterion_id"] for v in verdicts
                        if v["verdict"] == "FAIL" and v["gate"] != "advisory"]
            advisory_unmet = [v["criterion_id"] for v in verdicts
                              if v["verdict"] == "FAIL" and v["gate"] == "advisory"]
            # A missing verdict is not a pass, whatever the criterion's gate: the judge
            # failed to rule on it. Same rule the Studio and the student view apply.
            passed = not blocking and not result["missing_ids"]

            yield {
                "type": "verdicts", "phase": pid, "attempt": attempt,
                "verdicts": verdicts, "blocking": blocking,
                "advisory_unmet": advisory_unmet, "missing_ids": result["missing_ids"],
                "passed": passed,
            }

            if passed:
                break

            nudge = None
            if blocking:
                yield {"type": "working", "phase": pid, "attempt": attempt, "what": "nudging"}
                try:
                    n = nudging.nudge(phase, problem, artifact, criteria,
                                      result["verdicts"], attempt, prior)
                    spend(n["usage"])
                    nudge = {k: n[k] for k in
                             ("summary", "focus_id", "focus_text", "reason", "nudge", "failing")}
                    yield {"type": "nudge", "phase": pid, "attempt": attempt, **nudge}
                except JudgeError as exc:
                    # Not fatal. The verdicts stand, and the next attempt simply goes in
                    # without a nudge — which is itself worth seeing in the transcript.
                    yield {"type": "error", "phase": pid, "attempt": attempt, "fatal": False,
                           "message": f"No nudge this attempt: {exc}"}

            if attempt >= attempts_allowed:
                break

            feedback = {
                "failed": [{"text": v["criterion_text"], "evidence": v["evidence"]}
                           for v in verdicts if v["verdict"] == "FAIL"],
                "nudge": nudge,
                "previous": [{"label": f.get("label") or f["id"], "value": artifact.get(f["id"], "")}
                             for f in phase.get("artifact_fields") or []],
            }
            attempt += 1

        summary.append({"phase": pid, "label": label, "passed": passed, "attempts": attempt})
        yield {"type": "phase_done", "phase": pid, "label": label,
               "passed": passed, "attempts": attempt}

        if not passed:
            yield {"type": "done", "completed": False, "phases": summary, "usage": totals,
                   "message": f"{label} was not passed in {attempt} attempt(s), so the run stops here — "
                              "the phases after it are locked for a real student too."}
            return

        done[pid] = artifact

    yield {"type": "done", "completed": True, "phases": summary, "usage": totals,
           "message": "Every phase passed."}
