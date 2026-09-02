"""The nudge call: one failed submission, every failing gate named, one to fix first.

Sibling of `judge.py` and `hint.py` and built the same way — this module renders the
prompt, hands it to the provider, and checks the reply; the SDK lives in
`clive.providers`.

The philosophy is in `prompts/base/nudge.yaml`. Two parts of it are enforced here rather
than merely asked for, because both are the kind of thing a model drops quietly:

  A nudge may only name a GATING criterion the student actually failed. `failing_gates`
  selects that set inside `nudge()` so no caller can widen it, and a reply naming anything
  outside it is refused. This is the mirror of `hint.py`, which may only name advisory
  criteria — not a contradiction of it but the other half of the same rule. A hint is
  asked for before any verdict exists, so naming a gate there would tell a student what
  they are failing before anything judged them; a nudge runs on verdicts the student has
  already been shown, where naming one back reveals nothing new.

  Every failing gate is acknowledged. The model writes the prose summary, but the list
  itself is returned from here, computed in code — so a summary that forgets a criterion
  cannot hide one from the student, and the UI has the full set to render regardless of
  what the model chose to mention.
"""

from __future__ import annotations

from pydantic import BaseModel

from clive import prompts
from clive.providers import get_provider
from clive.providers.base import JudgeError

__all__ = ["Nudge", "JudgeError", "nudge"]


class Nudge(BaseModel):
    #: Two or three sentences accounting for every failing gate, so the student sees the
    #: whole gap rather than discovering the rest one resubmission at a time.
    summary: str
    #: The one failing gate to fix first.
    focus_id: str
    #: One sentence on why that one first.
    reason: str
    #: The nudge itself. Names the gap; never fills it.
    nudge: str


def nudge(
    phase: dict,
    problem: dict,
    artifact: dict,
    criteria: list[dict],
    verdicts: list[dict],
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Ask for one nudge about one judged submission.

    `criteria` is the phase's full criterion list and `verdicts` the judge result's
    verdicts; the failing gating subset is selected here rather than by the caller, so
    no caller can accidentally offer up a criterion the student passed or one that never
    blocked them.

    `history` is the conversation seam, threaded through to the template exactly as in
    `hint()`. It carries a transcript rather than holding a dialogue until the provider
    seam accepts a message list instead of one `user` string.

    Every argument is plain data — nothing here reads the filesystem except the shared
    nudge document — so a Sandbox scratch copy nudges the same as a saved one.
    """
    failures = prompts.failing_gates(criteria, verdicts)
    if not failures:
        # Reached when the caller nudges on a submission that passed its gates, or on one
        # held up only by `missing_ids`. Neither is a student error, and neither gives the
        # model anything to point at.
        raise JudgeError(
            "Nothing is blocking this submission, so there is nothing to nudge about. "
            "A nudge names a gating criterion the student failed; advisory criteria are "
            "reported with the verdicts and never hold anyone in a phase."
        )

    provider = get_provider()
    if not provider.has_api_key():
        raise JudgeError(
            f"No API key for provider {provider.name!r}. Set {provider.api_key_env} in the "
            "environment. Copy .env.example to .env, set the key, then restart the server."
        )

    doc = prompts.load_nudge()
    model_cfg = doc.get("model", {})
    model_id = model_cfg.get("id") or provider.default_model
    user_prompt = prompts.render_nudge_prompt(
        doc, phase, problem, artifact, failures, attempt, prior_artifacts, history
    )

    result = provider.judge_json(
        system=doc["system_prompt"],
        user=user_prompt,
        model=model_id,
        max_output_tokens=int(model_cfg.get("max_output_tokens", 2000)),
        effort=model_cfg.get("effort", "medium"),
        schema=Nudge,
    )

    parsed: Nudge = result.parsed
    offered = [c["id"] for c in failures]
    # A judge that invents an id produces a short verdict list, which `judge.py` can
    # report and move past. A nudge that invents one has aimed the student at a
    # requirement they are not failing, which is worse than saying nothing.
    if parsed.focus_id not in offered:
        raise JudgeError(
            f"The nudge names criterion {parsed.focus_id!r}, which is not among the "
            f"failing gating criteria. Expected one of: {', '.join(offered)}."
        )

    chosen = next(c for c in failures if c["id"] == parsed.focus_id)
    return {
        "model": result.model,
        "prompt": user_prompt,
        "summary": parsed.summary,
        "focus_id": parsed.focus_id,
        "focus_text": chosen.get("text", ""),
        "reason": parsed.reason,
        "nudge": parsed.nudge,
        # The whole blocking set, in rubric order, whatever the summary chose to name.
        # The caller renders these so the acknowledgement is structural, not prose the
        # model could have trimmed.
        "failing": [{"id": c["id"], "text": c.get("text", "")} for c in failures],
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    }
