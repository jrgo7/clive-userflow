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

#: Which provider the judge call goes to. `clive.providers.get_provider` resolves
#: this to a concrete provider; per-provider model defaults, model choices, and
#: API-key env vars live on those classes.
PROVIDER = os.environ.get("CLIVE_PROVIDER", "anthropic").strip().strip("'\"")

EFFORT_CHOICES = ["low", "medium", "high", "xhigh", "max"]
