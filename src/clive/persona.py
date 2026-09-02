"""The simulated-student call: one persona, one phase, one artifact.

Sibling of `judge.py`, `hint.py` and `nudge.py`, and built the same way — this module
renders the prompt, hands it to the provider, and checks the reply.

It is the one call in this system that produces work rather than judging it, and the
constraint that matters is what it is *not* given: the criteria. `render_persona_prompt`
takes no rubric, so a persona writes from the problem and the phase instructions like a
student does. A simulated student shown the rubric writes to the rubric, and a run against
it would only tell you the model can read a checklist.

It does see the verdicts and the nudge from its last attempt, because a real student sees
those on screen. That is what makes a simulation a test of whether the nudge helps.
"""

from __future__ import annotations

from pydantic import BaseModel, create_model

from clive import prompts
from clive.providers import get_provider
from clive.providers.base import JudgeError

__all__ = ["JudgeError", "artifact_schema", "write"]


def artifact_schema(artifact_fields: list[dict]) -> type[BaseModel]:
    """A pydantic model with one required string per artifact field.

    Built per phase rather than declared once, because the fields are authored content —
    a phase that gains a box in the Studio gains a key here with no code change. The ids
    are re-validated because this turns them into model attribute names, and a phase file
    edited by hand has not been through `save_phase`.
    """
    if not artifact_fields:
        raise JudgeError(
            "This phase has no artifact fields, so there is nothing for a student to write. "
            "Add at least one in the Studio's Prompt tab."
        )
    fields = {
        prompts.check_slug(f.get("id", ""), "artifact field id"): (str, ...)
        for f in artifact_fields
    }
    return create_model("StudentArtifact", **fields)


def write(
    persona: dict,
    phase: dict,
    problem: dict,
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
    feedback: dict | None = None,
    persona_doc: dict | None = None,
    help: dict | None = None,
) -> dict:
    """Ask one persona to write one phase's artifact.

    `feedback` carries the previous attempt's failed criteria, the nudge, and what the
    persona wrote last time; passing none renders the first-attempt prompt.

    `help` is `{"diagnosis", "hint"}` from a hint the character asked for — its prose
    only. The criterion the hint points at is deliberately not carried: a persona that
    could read the rule would satisfy it, and the run would report the hint as more use
    than it is.

    Every argument is plain data except the shared persona document, which is loaded here
    when not supplied — a caller running many phases passes it once rather than re-reading
    the file per call.
    """
    provider = get_provider()
    if not provider.has_api_key():
        raise JudgeError(
            f"No API key for provider {provider.name!r}. Set {provider.api_key_env} in the "
            "environment. Copy .env.example to .env, set the key, then restart the server."
        )

    doc = persona_doc or prompts.load_personas()
    model_cfg = doc.get("model", {})
    model_id = model_cfg.get("id") or provider.default_model
    schema = artifact_schema(phase.get("artifact_fields") or [])

    user_prompt = prompts.render_persona_prompt(
        doc, persona, phase, problem, attempt, prior_artifacts, feedback, help
    )

    result = provider.judge_json(
        system=doc["system_prompt"],
        user=user_prompt,
        model=model_id,
        max_output_tokens=int(model_cfg.get("max_output_tokens", 3000)),
        effort=model_cfg.get("effort", "medium"),
        schema=schema,
    )

    # The schema makes every field required, so a reply that parsed has them all. Values
    # are still normalised to strings: a model that answers a numeric-looking field with a
    # number would otherwise put an int where the judge template expects text.
    artifact = {k: ("" if v is None else str(v)) for k, v in result.parsed.model_dump().items()}

    return {
        "artifact": artifact,
        "model": result.model,
        "prompt": user_prompt,
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    }
