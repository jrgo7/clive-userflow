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

#: Which sandbox backend compiles and runs student C. Unset means "probe and take the
#: strongest that works" -- see clive.executors.get_executor.
EXECUTOR = os.environ.get("CLIVE_EXECUTOR", "").strip().strip("'\"")

#: The image the container backend runs in. It pins gcc, which is the only way two
#: participants on two machines get the same verdict for the same code.
EXECUTOR_IMAGE = os.environ.get(
    "CLIVE_EXECUTOR_IMAGE", "docker.io/library/gcc:14"
).strip().strip("'\"")

#: The weakest isolation this host will accept: "container", "namespace", or "rlimit".
#: Serving several participants from one box, set this to "namespace" or better -- the
#: default is permissive because the common case is one author on their own machine.
SANDBOX_FLOOR = os.environ.get("CLIVE_SANDBOX_FLOOR", "rlimit").strip().strip("'\"")

#: Compiles running at once. ThreadingHTTPServer spawns a thread per request and would
#: otherwise start an unbounded number of them.
MAX_CONCURRENT_RUNS = int(os.environ.get("CLIVE_MAX_CONCURRENT_RUNS", "4"))
