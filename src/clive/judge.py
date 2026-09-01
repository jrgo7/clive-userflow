"""The judge call: one phase, one artifact, one verdict per criterion.

Mirrors prompts/base/output_schema.json. The schema file is what the phase YAML
pins; `JudgeResult` below is what the SDK validates against. Keep the two in step.

The model call itself lives in `clive.providers`, picked from the phase's
`model.id` (falling back to `CLIVE_PROVIDER`). This module renders the prompt,
hands it to the provider, and audits the reply.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from clive import prompts
from clive.providers import get_provider
from clive.providers.base import JudgeError  # re-exported for existing callers

__all__ = ["Verdict", "JudgeResult", "JudgeError", "audit_evidence", "judge"]


class Verdict(BaseModel):
    criterion_id: str
    verdict: Literal["PASS", "FAIL"]
    evidence: str
    confidence: Literal["low", "medium", "high"]


class JudgeResult(BaseModel):
    verdicts: list[Verdict]


def _normalise(text: str) -> str:
    """Collapse whitespace so an evidence quote that differs only in wrapping
    still matches the artifact it was taken from."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def audit_evidence(verdicts: list[Verdict], artifact: dict) -> dict[str, bool]:
    """Check each evidence span actually appears in the artifact.

    The prompt requires verbatim quotation. A quote that is not in the artifact
    means the model asserted rather than observed, and this catches it without
    another API call. An empty quote is not a fabrication, so it audits clean.
    """
    haystack = _normalise(" ".join(str(v) for v in (artifact or {}).values()))
    return {
        v.criterion_id: (not v.evidence.strip()) or (_normalise(v.evidence) in haystack)
        for v in verdicts
    }


def judge(
    phase: dict,
    problem: dict,
    artifact: dict,
    criteria: list[dict],
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
) -> dict:
    """Judge one submission against every criterion in a single call.

    Every argument is plain data — nothing here reads the filesystem — so the same
    function serves a saved phase from disk and an unsaved Sandbox scratch copy.
    """
    if not criteria:
        raise JudgeError("This phase has no criteria yet. Add at least one before running.")

    model_cfg = phase.get("model", {})
    model_id = model_cfg.get("id")
    provider = get_provider(model=model_id)
    if not provider.has_api_key():
        raise JudgeError(
            f"No API key for provider {provider.name!r}. Set {provider.api_key_env} in the "
            "environment. Copy .env.example to .env, set the key, then restart the server."
        )
    model_id = model_id or provider.default_model
    user_prompt = prompts.render_user_prompt(
        phase, problem, artifact, criteria, attempt, prior_artifacts
    )

    result = provider.judge_json(
        system=phase["system_prompt"],
        user=user_prompt,
        model=model_id,
        max_output_tokens=int(model_cfg.get("max_output_tokens", 4000)),
        effort=model_cfg.get("effort", "medium"),
        schema=JudgeResult,
    )

    parsed: JudgeResult = result.parsed
    quoted = audit_evidence(parsed.verdicts, artifact)
    asked = [c["id"] for c in criteria]
    returned = [v.criterion_id for v in parsed.verdicts]

    return {
        "model": result.model,
        "prompt": user_prompt,
        "verdicts": [
            {**v.model_dump(), "evidence_found": quoted[v.criterion_id]} for v in parsed.verdicts
        ],
        # A judge that invents or drops an id has broken its contract; surfacing it
        # here means a bad prompt edit shows up as a warning instead of silently
        # producing a short verdict list.
        "missing_ids": [cid for cid in asked if cid not in returned],
        "unexpected_ids": [cid for cid in returned if cid not in asked],
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    }
