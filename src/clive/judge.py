"""The judge call: one phase, one artifact, one verdict per criterion.

Mirrors prompts/base/output_schema.json. The schema file is what the phase YAML
pins; `JudgeResult` below is what the SDK validates against. Keep the two in step.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from clive import prompts
from clive.config import DEFAULT_MODEL, has_api_key


class Verdict(BaseModel):
    criterion_id: str
    verdict: Literal["PASS", "FAIL"]
    evidence: str
    confidence: Literal["low", "medium", "high"]


class JudgeResult(BaseModel):
    verdicts: list[Verdict]


class JudgeError(RuntimeError):
    """A judging run failed for a reason worth showing the user verbatim."""


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
    if not has_api_key("anthropic"):
        raise JudgeError(
            "No ANTHROPIC_API_KEY in the environment. "
            "Copy .env.example to .env, set the key, then restart the server."
        )

    try:
        import anthropic
    except ModuleNotFoundError:
        raise JudgeError("The `anthropic` package is not installed. Run `uv sync`.") from None

    model_cfg = phase.get("model", {})
    model_id = model_cfg.get("id") or DEFAULT_MODEL
    user_prompt = prompts.render_user_prompt(
        phase, problem, artifact, criteria, attempt, prior_artifacts
    )

    client = anthropic.Anthropic()
    try:
        resp = client.messages.parse(
            model=model_id,
            max_tokens=int(model_cfg.get("max_output_tokens", 4000)),
            system=phase["system_prompt"],
            messages=[{"role": "user", "content": user_prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": model_cfg.get("effort", "medium")},
            output_format=JudgeResult,
        )
    except anthropic.AuthenticationError:
        raise JudgeError(
            "The API key was rejected. Check ANTHROPIC_API_KEY in .env."
        ) from None
    except anthropic.NotFoundError:
        raise JudgeError(
            f"The model {model_id!r} does not exist or is not available to this key. "
            "Pick another model in the Prompt tab."
        ) from None
    except anthropic.RateLimitError as exc:
        retry_after = exc.response.headers.get("retry-after", "60")
        raise JudgeError(f"Rate limited; retry after {retry_after}s.") from None
    except anthropic.APIStatusError as exc:
        raise JudgeError(f"API error {exc.status_code}: {exc.message}") from None
    except anthropic.APIConnectionError:
        raise JudgeError("Could not reach the API. Check your connection.") from None

    if resp.stop_reason == "refusal":
        detail = getattr(resp, "stop_details", None)
        reason = getattr(detail, "explanation", None) or "no explanation given"
        raise JudgeError(f"The model declined to answer ({reason}).")
    if resp.stop_reason == "max_tokens":
        raise JudgeError(
            "Response hit max_tokens and the verdict list is truncated. "
            "Raise max_output_tokens in the Prompt tab, or lower effort."
        )

    result: JudgeResult = resp.parsed_output
    quoted = audit_evidence(result.verdicts, artifact)
    asked = [c["id"] for c in criteria]
    returned = [v.criterion_id for v in result.verdicts]

    return {
        "model": resp.model,
        "prompt": user_prompt,
        "verdicts": [
            {**v.model_dump(), "evidence_found": quoted[v.criterion_id]} for v in result.verdicts
        ],
        # A judge that invents or drops an id has broken its contract; surfacing it
        # here means a bad prompt edit shows up as a warning instead of silently
        # producing a short verdict list.
        "missing_ids": [cid for cid in asked if cid not in returned],
        "unexpected_ids": [cid for cid in returned if cid not in asked],
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }
