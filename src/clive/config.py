"""Repository paths and environment configuration.

Everything CLive reads from disk is resolved relative to `REPO_ROOT`, so the
notebooks, the Studio app, and any future CLI all agree on where prompts,
criteria, and cases live regardless of the working directory they were started
from.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/clive/config.py -> src/clive -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]

PROMPTS_DIR = REPO_ROOT / "prompts"
PHASES_DIR = PROMPTS_DIR / "phases"
BASE_PROMPTS_DIR = PROMPTS_DIR / "base"
CRITERIA_DIR = REPO_ROOT / "criteria"
CASES_DIR = REPO_ROOT / "cases"
PROBLEMS_DIR = CASES_DIR / "problems"
SUITES_DIR = CASES_DIR / "suites"

# `override=False` so an ANTHROPIC_API_KEY already exported in the shell wins
# over a stale one committed to a local .env.
load_dotenv(REPO_ROOT / ".env", override=False)

PROVIDER = os.environ.get("CLIVE_PROVIDER", "anthropic").strip().strip("'\"")

#: Used when a phase YAML does not pin `model.id`.
DEFAULT_MODEL = "claude-opus-5"

#: Offered in the Studio's model dropdown. Not exhaustive — a phase YAML may
#: name any model id the provider accepts.
MODEL_CHOICES = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-haiku-4-5",
]

EFFORT_CHOICES = ["low", "medium", "high", "xhigh", "max"]


def api_key(provider: str | None = None) -> str | None:
    """The API key for `provider`, or None if it is not set."""
    env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }.get((provider or PROVIDER).lower())
    if env_var is None:
        return None
    key = os.environ.get(env_var)
    return key or None


def has_api_key(provider: str | None = None) -> bool:
    return api_key(provider) is not None
