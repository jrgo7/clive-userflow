"""The hint call: one stuck student, one advisory criterion, one nudge.

Sibling of `judge.py` and built the same way — this module renders the prompt,
hands it to the provider, and checks the reply; the SDK lives in `clive.providers`.

The philosophy is in `prompts/base/hint.yaml` and worth restating here, because it
is what the code below enforces rather than merely hopes for: a hint points at a
NON-BLOCKING criterion. The model is never shown the gating criteria, so it cannot
hand the student the requirement they are failing, and `hint()` refuses a reply that
names anything outside the advisory set it supplied.

That holds because a hint runs with no verdicts in hand. After a judge call it is
`nudge.py` that speaks, under the opposite restriction — gating criteria only, and only
ones the student actually failed — because by then those verdicts are already on screen.
"""

from __future__ import annotations

from pydantic import BaseModel

from clive import prompts
from clive.providers import get_provider
from clive.providers.base import JudgeError

__all__ = ["Hint", "JudgeError", "hint"]


class Hint(BaseModel):
    #: The advisory criterion the student is being pointed at.
    criterion_id: str
    #: One sentence, addressed to the student, on why they appear stuck.
    diagnosis: str
    #: The nudge itself. Names the gap; never fills it.
    hint: str


def hint(
    phase: dict,
    problem: dict,
    artifact: dict,
    criteria: list[dict],
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Ask for one hint about one artifact.

    `criteria` is the phase's full criterion list; the advisory subset is selected
    here rather than by the caller, so no caller can accidentally offer a gating
    criterion up to be hinted at.

    `history` is the conversation seam. It is threaded through to the template,
    which renders it into this single user turn. Genuine multi-turn hinting also
    needs the provider seam to accept a message list instead of one `user` string,
    so today this carries a transcript rather than holding a dialogue.

    Every argument is plain data — nothing here reads the filesystem except the
    shared hint document — so a Sandbox scratch copy judges the same as a saved one.
    """
    advisory = prompts.advisory_criteria(criteria)
    if not advisory:
        raise JudgeError(
            "This phase has no advisory criteria, so there is nothing to hint at. "
            "A hint points at optional depth, never at a requirement the student is "
            "failing. Add a criterion with gate `advisory` first."
        )

    provider = get_provider()
    if not provider.has_api_key():
        raise JudgeError(
            f"No API key for provider {provider.name!r}. Set {provider.api_key_env} in the "
            "environment. Copy .env.example to .env, set the key, then restart the server."
        )

    doc = prompts.load_hint()
    model_cfg = doc.get("model", {})
    model_id = model_cfg.get("id") or provider.default_model
    user_prompt = prompts.render_hint_prompt(
        doc, phase, problem, artifact, advisory, attempt, prior_artifacts, history
    )

    result = provider.judge_json(
        system=doc["system_prompt"],
        user=user_prompt,
        model=model_id,
        max_output_tokens=int(model_cfg.get("max_output_tokens", 2000)),
        effort=model_cfg.get("effort", "medium"),
        schema=Hint,
    )

    parsed: Hint = result.parsed
    offered = [c["id"] for c in advisory]
    # A judge that invents an id produces a short verdict list, which `judge.py` can
    # report and move past. A hint that invents one has produced its whole answer
    # about a criterion the student cannot see, so there is nothing to salvage.
    if parsed.criterion_id not in offered:
        raise JudgeError(
            f"The hint names criterion {parsed.criterion_id!r}, which was not offered. "
            f"Expected one of: {', '.join(offered)}."
        )

    chosen = next(c for c in advisory if c["id"] == parsed.criterion_id)
    return {
        "model": result.model,
        "prompt": user_prompt,
        "criterion_id": parsed.criterion_id,
        "criterion_text": chosen.get("text", ""),
        "diagnosis": parsed.diagnosis,
        "hint": parsed.hint,
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    }
