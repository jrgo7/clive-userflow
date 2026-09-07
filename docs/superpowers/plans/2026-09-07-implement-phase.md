# Implement Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth PCDIT phase to the clive-userflow prototype — a Monaco C editor whose gate is a compiler running the problem's test cases, with an LLM demoted to advisory review of the code against the student's own Problem/Cases/Design artifacts.

**Architecture:** A new `gate: tests` key on a phase switches `student.submit` from the judge path to a grading path. `src/clive/executors/` compiles and runs untrusted C behind a swappable sandbox backend (container first, bwrap, then bare rlimits), mirroring the existing `src/clive/providers/` registry pattern. `src/clive/grade.py` is the pure seam between a problem's test cases and an executor. The judge is called only when every test already passes.

**Tech Stack:** Python 3.13 stdlib (`subprocess`, `resource`, `tempfile`, `threading`), PyYAML, Jinja2, Pydantic, a stdlib `ThreadingHTTPServer`, and Monaco loaded from CDN in vanilla JS. No new Python dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-implement-phase-design.md`

## Global Constraints

- **This repository is a prototype**, not CLive and not AnimoRank. Rigour is deliberately uneven: the sandbox and the hidden-test-case leak guard are production-grade; everything else is built to be cheap to discard.
- **No new Python dependencies.** `pyproject.toml` gains nothing.
- **Compile line, verbatim:** `gcc -Werror -Wall -o program *.c -lm -lpthread`. Run line: `./program`.
- **Comparison normalises trailing whitespace** — strip trailing whitespace per line, then trailing blank lines. Interior whitespace is significant. A strict comparison rejects correct programs on all nine existing problems.
- **`hidden_test_cases` must never reach the browser.** Not in `problem()`, not in `boot()`, not in a nudge prompt, not in the served HTML.
- **`criteria/implement.yaml` is entirely `gate: advisory`.** A gating criterion there would let the judge block code that passes every test.
- **Default limits:** compile 10s, run 5s, memory 256 MB (run only — never applied to gcc), pids 64, output 64 KB, 4 concurrent runs.
- **YAML comments:** only the leading comment block of a file survives a Studio round-trip (`read_header` in `prompts.py`). Put explanation at the top of the file, never beside the key it describes.
- **Bump `version` in a `criteria/<phase>.yaml` when a rule's meaning changes**, and record why a prompt changed in `prompts/CHANGELOG.md`.
- **Run tests with:** `uv run pytest`.

---

### Task 1: Phase `gate` and artifact-field `kind`

The switch Approach 1 turns on. `gate: tests` selects the grading path in a later task; `kind: code` selects the Monaco editor in the page. Both default so that every existing YAML file is unchanged.

**Files:**
- Modify: `src/clive/prompts.py` (`load_phase`, `save_phase`, plus two new constants near `GATES`)
- Test: `tests/test_prompts_gate.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `prompts.PHASE_GATES = ("criteria", "tests")`, `prompts.DEFAULT_PHASE_GATE = "criteria"`, `prompts.FIELD_KINDS = ("text", "code")`, `prompts.DEFAULT_FIELD_KIND = "text"`. `load_phase(phase)` returns a dict whose `["gate"]` is always present, and each entry of `["artifact_fields"]` always has a `"kind"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompts_gate.py`:

```python
"""The phase `gate` key and the artifact-field `kind` key.

Both exist to be defaulted: every phase written before they existed must keep
behaving exactly as it did, which is what most of these tests pin.
"""

from __future__ import annotations

import pytest

from clive import prompts


def test_existing_phase_defaults_to_criteria_gate():
    phase = prompts.load_phase("algorithm_design")
    assert phase["gate"] == "criteria"


def test_existing_artifact_fields_default_to_text_kind():
    phase = prompts.load_phase("algorithm_design")
    assert phase["artifact_fields"]
    assert all(f["kind"] == "text" for f in phase["artifact_fields"])


def test_save_phase_rejects_an_unknown_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    with pytest.raises(prompts.ContentError, match="gate"):
        prompts.save_phase("scratch", {
            "gate": "vibes",
            "system_prompt": "s",
            "user_template": "u",
        })


def test_save_phase_rejects_an_unknown_field_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    with pytest.raises(prompts.ContentError, match="kind"):
        prompts.save_phase("scratch", {
            "artifact_fields": [{"id": "code", "kind": "hologram"}],
            "system_prompt": "s",
            "user_template": "u",
        })


def test_save_phase_round_trips_gate_and_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PHASES_DIR", tmp_path)
    saved = prompts.save_phase("scratch", {
        "gate": "tests",
        "artifact_fields": [{"id": "code", "label": "Code", "kind": "code", "language": "c"}],
        "system_prompt": "s",
        "user_template": "u",
    })
    assert saved["gate"] == "tests"
    assert saved["artifact_fields"][0]["kind"] == "code"
    assert saved["artifact_fields"][0]["language"] == "c"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prompts_gate.py -v`
Expected: FAIL — `KeyError: 'gate'` on the first test.

- [ ] **Step 3: Add the constants**

In `src/clive/prompts.py`, immediately after the existing `DEFAULT_GATE = "gating"` block, add:

```python
#: What decides whether a phase passes. `criteria` is the original behaviour: the judge
#: rules on every criterion and the gating ones hold the student. `tests` hands the gate
#: to a compiler -- the phase passes when every test case passes, and its criteria are
#: advisory review rather than a barrier. (See docs/superpowers/specs/2026-09-07-*.md)
PHASE_GATES = ("criteria", "tests")

#: A phase that does not say is judged, which is what every phase written before this
#: key existed meant.
DEFAULT_PHASE_GATE = "criteria"

#: How an artifact field is edited. `text` is the textarea every field has always been;
#: `code` mounts an editor. Anything but the renderer should treat them identically.
FIELD_KINDS = ("text", "code")

DEFAULT_FIELD_KIND = "text"
```

- [ ] **Step 4: Default them in `load_phase`**

In `load_phase`, after the existing `data.setdefault("artifact_fields", [])` line, add:

```python
    data.setdefault("gate", DEFAULT_PHASE_GATE)
    for field in data["artifact_fields"]:
        field.setdefault("kind", DEFAULT_FIELD_KIND)
```

- [ ] **Step 5: Validate them in `save_phase`**

In `save_phase`, replace the existing artifact-field loop:

```python
    for field in merged.get("artifact_fields") or []:
        check_slug(field.get("id", ""), "artifact field id")
```

with:

```python
    gate = str(merged.get("gate") or DEFAULT_PHASE_GATE).strip()
    if gate not in PHASE_GATES:
        raise ContentError(
            f"Phase {phase!r} has gate {gate!r}; expected one of {', '.join(PHASE_GATES)}."
        )
    merged["gate"] = gate

    for field in merged.get("artifact_fields") or []:
        check_slug(field.get("id", ""), "artifact field id")
        kind = str(field.get("kind") or DEFAULT_FIELD_KIND).strip()
        if kind not in FIELD_KINDS:
            raise ContentError(
                f"Artifact field {field.get('id')!r} has kind {kind!r}; "
                f"expected one of {', '.join(FIELD_KINDS)}."
            )
        field["kind"] = kind
```

Then add `"gate"` to `key_order` in `save_phase`, immediately after `"order"`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prompts_gate.py -v`
Expected: 5 passed.

- [ ] **Step 7: Verify no existing file changed meaning**

Run: `uv run pytest`
Expected: the whole suite passes. Then run `git diff --stat` and confirm no YAML under `prompts/` or `criteria/` was touched.

- [ ] **Step 8: Commit**

```bash
git add src/clive/prompts.py tests/test_prompts_gate.py
git commit -m "Add phase gate and artifact-field kind, both defaulted

gate: tests hands a phase's pass/fail to a compiler instead of the judge;
kind: code marks the one field that gets an editor. Both default so every
existing phase file keeps its exact current behaviour."
```

---

### Task 2: `starter_code` and `hidden_test_cases` on a problem

**Files:**
- Modify: `src/clive/prompts.py` (`load_problem`, `save_problem`)
- Test: `tests/test_prompts_problem.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `load_problem(slug)` always returns `"starter_code"` (str) and `"hidden_test_cases"` (list of `{"input", "output"}`). `save_problem` persists both, with `starter_code` and `hidden_test_cases` appended to the key order after `public_test_cases`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompts_problem.py`:

```python
"""The two problem keys the Implement phase adds.

Both are optional: the nine problems in the corpus predate them, and a save must
not invent content for a file that has neither.
"""

from __future__ import annotations

from clive import prompts


def test_existing_problem_defaults_both_keys():
    problem = prompts.load_problem("count_vowels")
    assert problem["starter_code"] == ""
    assert problem["hidden_test_cases"] == []


def test_save_round_trips_both_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {
        "title": "Scratch",
        "statement": "Do a thing.\n",
        "public_test_cases": [{"input": "1", "output": "2"}],
        "hidden_test_cases": [{"input": "9", "output": "10"}],
        "starter_code": "#include <stdio.h>\n",
    })
    loaded = prompts.load_problem("scratch")
    assert loaded["hidden_test_cases"] == [{"input": "9", "output": "10"}]
    assert loaded["starter_code"] == "#include <stdio.h>\n"


def test_save_drops_blank_hidden_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {
        "statement": "s\n",
        "hidden_test_cases": [{"input": "", "output": ""}, {"input": "a", "output": "b"}],
    })
    assert prompts.load_problem("scratch")["hidden_test_cases"] == [{"input": "a", "output": "b"}]


def test_save_omits_the_keys_when_empty(tmp_path, monkeypatch):
    """A problem with neither key must not gain two noise keys on every save."""
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("scratch", {"statement": "s\n"})
    text = (tmp_path / "scratch.yaml").read_text()
    assert "hidden_test_cases" not in text
    assert "starter_code" not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prompts_problem.py -v`
Expected: FAIL — `KeyError: 'starter_code'`.

- [ ] **Step 3: Extract the case-cleaning loop**

In `src/clive/prompts.py`, above `save_problem`, add:

```python
def _clean_cases(rows: Any) -> list[dict]:
    """Normalise a list of test cases, dropping rows the user left blank.

    Shared by the public and hidden lists so the two cannot drift apart -- a hidden
    case that normalised differently from a public one would grade differently for
    no reason a reader could see.
    """
    cases = []
    for case in rows or []:
        if not str(case.get("input", "")).strip() and not str(case.get("output", "")).strip():
            continue
        cases.append(
            {
                "input": str(case.get("input", "")).replace("\r\n", "\n"),
                "output": str(case.get("output", "")).replace("\r\n", "\n"),
            }
        )
    return cases
```

- [ ] **Step 4: Use it in `save_problem` and add the two keys**

In `save_problem`, replace the inline `cases = []` loop with `cases = _clean_cases(data.get("public_test_cases"))`, then add before `ordered`:

```python
    hidden = _clean_cases(data.get("hidden_test_cases"))
    starter = str(data.get("starter_code") or "").replace("\r\n", "\n")
```

and extend `ordered` after `"public_test_cases": cases,`:

```python
        # Omitted entirely when empty: a problem that has neither key should not gain
        # two of them on the next Studio save, which would dirty all nine files at once.
        **({"hidden_test_cases": hidden} if hidden else {}),
        **({"starter_code": starter} if starter.strip() else {}),
```

- [ ] **Step 5: Default them in `load_problem`**

Replace the body of `load_problem` with:

```python
def load_problem(problem_id: str) -> dict:
    data = read_yaml(problem_path(problem_id))
    data.setdefault("public_test_cases", [])
    data.setdefault("hidden_test_cases", [])
    data.setdefault("starter_code", "")
    data["slug"] = problem_id
    return data
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_prompts_problem.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/clive/prompts.py tests/test_prompts_problem.py
git commit -m "Add starter_code and hidden_test_cases to problems

Both optional and both omitted from the dump when empty, so the nine existing
problem files round-trip byte-identically. The case-cleaning loop is shared
between the public and hidden lists so the two cannot normalise differently."
```

---

### Task 3: The executor interface and a bare POSIX backend

The first backend deliberately has the weakest isolation, so the interface is proven before the sandboxing is layered on. `isolation` reports `"rlimit"` honestly, and Task 5's floor setting is what refuses it in production.

**Files:**
- Create: `src/clive/executors/__init__.py`, `src/clive/executors/base.py`, `src/clive/executors/local.py`
- Modify: `src/clive/config.py`
- Test: `tests/test_executors.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `executors.base.Limits(compile_seconds=10, run_seconds=5, memory_mb=256, pids=64, output_bytes=65536)`
  - `executors.base.ExecutionRequest(files: dict[str,str], compile_argv: list[str], run_argv: list[str], stdins: list[str], limits: Limits)`
  - `executors.base.RunOutcome(status, stdout, stderr, exit_code, duration_ms)` where status is one of `"ok" | "timeout" | "runtime_error" | "output_truncated"`
  - `executors.base.ExecutionResult(compiled: bool, compile_error: str, warnings: str, runs: list[RunOutcome])`
  - `executors.base.ExecutorError`
  - `executors.base.Executor` ABC with `name`, `isolation`, classmethod `probe() -> bool`, `execute(request) -> ExecutionResult`, and concrete `run(request)` which acquires the concurrency semaphore then calls `execute`.
  - `executors.get_executor() -> Executor`, `executors.REGISTRY`
  - `config.EXECUTOR`, `config.EXECUTOR_IMAGE`, `config.SANDBOX_FLOOR`, `config.MAX_CONCURRENT_RUNS`

- [ ] **Step 1: Add the configuration**

Append to `src/clive/config.py`:

```python
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
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_executors.py`:

```python
"""The sandbox backends, exercised against real C.

Every test here compiles and runs actual code, so the whole module skips on a host
with no working backend -- a machine without a compiler should not fail the suite.
"""

from __future__ import annotations

import pytest

from clive.executors import available_executors
from clive.executors.base import ExecutionRequest, Limits

COMPILE = ["gcc", "-Werror", "-Wall", "-o", "program", "main.c", "-lm", "-lpthread"]
RUN = ["./program"]

EXECUTORS = available_executors()

pytestmark = pytest.mark.skipif(not EXECUTORS, reason="no working executor on this host")


def request_for(source: str, stdins: list[str], **limits) -> ExecutionRequest:
    return ExecutionRequest(
        files={"main.c": source},
        compile_argv=COMPILE,
        run_argv=RUN,
        stdins=stdins,
        limits=Limits(**limits),
    )


@pytest.fixture(params=EXECUTORS, ids=lambda e: e.name)
def executor(request):
    return request.param()


ECHO = """
#include <stdio.h>
int main(void) { int n; if (scanf("%d", &n) != 1) return 1; printf("%d\\n", n * 2); return 0; }
"""


def test_compiles_and_runs_every_stdin(executor):
    result = executor.run(request_for(ECHO, ["3", "10"]))
    assert result.compiled, result.compile_error
    assert [r.stdout.strip() for r in result.runs] == ["6", "20"]
    assert all(r.status == "ok" for r in result.runs)


def test_compile_error_is_reported_and_nothing_runs(executor):
    result = executor.run(request_for("int main(void) { return", ["1"]))
    assert not result.compiled
    assert result.compile_error.strip()
    assert result.runs == []


def test_werror_turns_a_warning_into_a_compile_error(executor):
    source = "#include <stdio.h>\nint main(void) { int unused; printf(\"hi\\n\"); return 0; }"
    result = executor.run(request_for(source, ["1"]))
    assert not result.compiled


def test_infinite_loop_times_out(executor):
    result = executor.run(request_for("int main(void) { for (;;) ; }", ["1"], run_seconds=2))
    assert result.compiled, result.compile_error
    assert result.runs[0].status == "timeout"


def test_nonzero_exit_is_a_runtime_error(executor):
    result = executor.run(request_for("int main(void) { return 3; }", ["1"]))
    assert result.runs[0].status == "runtime_error"
    assert result.runs[0].exit_code == 3


def test_output_flood_is_truncated_not_buffered_forever(executor):
    source = """
#include <stdio.h>
int main(void) { for (long i = 0; i < 5000000L; i++) printf("flood\\n"); return 0; }
"""
    result = executor.run(request_for(source, ["1"], output_bytes=4096, run_seconds=10))
    assert result.compiled, result.compile_error
    assert len(result.runs[0].stdout) <= 4096
    assert result.runs[0].status in ("output_truncated", "timeout")


def test_a_crash_is_a_runtime_error_not_an_exception(executor):
    source = "int main(void) { int *p = 0; *p = 1; return 0; }"
    result = executor.run(request_for(source, ["1"]))
    assert result.runs[0].status == "runtime_error"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_executors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clive.executors'`.

- [ ] **Step 4: Write `base.py`**

Create `src/clive/executors/base.py`:

```python
"""The executor seam: source files in, a compile result and one run per stdin out.

Shaped after AnimoRank's `CodeExecutor` (src/lib/testCase/executor/index.ts), which
takes files plus a compile script plus a run script and returns a discriminated union
of compile error / timeout / runtime error / success. Two divergences, both recorded
in the spec: this compiles once and runs N times rather than once per case, and the
per-run wall clock is seconds rather than AnimoRank's 30.

A backend translates its own failures into `ExecutorError` and never lets a subprocess
exception escape -- the same contract `clive.providers.Provider` has with `JudgeError`.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from clive import config

__all__ = [
    "ExecutorError", "Limits", "ExecutionRequest",
    "RunOutcome", "ExecutionResult", "Executor",
]


class ExecutorError(RuntimeError):
    """A run failed for a reason worth showing the user verbatim."""


#: Held across the compile and every run of one request, so N concurrent HTTP requests
#: cannot start N concurrent compiles. Module-level because the limit is the host's,
#: not any one executor instance's.
_SEMAPHORE = threading.BoundedSemaphore(config.MAX_CONCURRENT_RUNS)


@dataclass(frozen=True)
class Limits:
    #: gcc gets its own, longer clock, and is never given `memory_mb`: the compiler
    #: routinely needs more than a student's program is allowed, and an RLIMIT_AS that
    #: killed gcc would surface as a compile error on correct code.
    compile_seconds: int = 10
    run_seconds: int = 5
    memory_mb: int = 256
    pids: int = 64
    output_bytes: int = 64 * 1024


@dataclass(frozen=True)
class ExecutionRequest:
    #: filename -> contents. The student's program is `main.c`; the map exists rather
    #: than a bare string so a generated harness can be added without changing this.
    files: dict[str, str]
    compile_argv: list[str]
    run_argv: list[str]
    #: One run per entry. Compile happens once, before any of them.
    stdins: list[str]
    limits: Limits = field(default_factory=Limits)


RunStatus = Literal["ok", "timeout", "runtime_error", "output_truncated"]


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


@dataclass(frozen=True)
class ExecutionResult:
    compiled: bool
    #: The compiler's stderr when it failed. Empty when it compiled.
    compile_error: str
    #: The compiler's stderr when it succeeded anyway. Empty when clean. This is what
    #: lets the page show a warning as its own state rather than as a wrong answer.
    warnings: str
    #: Empty when compilation failed -- nothing ran.
    runs: list[RunOutcome]


class Executor(ABC):
    #: Registry key, and the value CLIVE_EXECUTOR is matched against.
    name: str
    #: How strong the isolation actually is. Ranked in clive.executors; a host serving
    #: several participants sets CLIVE_SANDBOX_FLOOR to refuse the weak end.
    isolation: Literal["container", "namespace", "rlimit"]

    @classmethod
    @abstractmethod
    def probe(cls) -> bool:
        """Whether this backend can actually run here, right now.

        Must test by doing rather than by looking: bwrap can be installed and still
        fail, because unprivileged user namespaces are restricted by AppArmor on
        Ubuntu 23.10+ and were off by default on older Debian.
        """

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Compile once, then run once per stdin. Never raises for student error."""

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """`execute` behind the host-wide concurrency limit. Callers use this."""
        with _SEMAPHORE:
            return self.execute(request)
```

- [ ] **Step 5: Write `local.py`**

Create `src/clive/executors/local.py`:

```python
"""The local backends: a subprocess on this host, isolated as well as this host allows.

Two executors in one file because they differ only in the argv prefix. `local-bwrap`
wraps every command in a bubblewrap sandbox with no network and a read-only system;
`local` runs the command directly and admits, through `isolation = "rlimit"`, that it
offers no network or filesystem isolation at all.

Both apply rlimits and both start a new session so a timeout can kill the whole process
group -- a student's program that forks is otherwise still running after the wait
returns.
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from clive.executors.base import (
    ExecutionRequest,
    ExecutionResult,
    Executor,
    ExecutorError,
    Limits,
    RunOutcome,
)


def _rlimits(limits: Limits):
    """Applied in the child, between fork and exec. Run step only."""

    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_mb << 20,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits.run_seconds + 1,) * 2)
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.pids,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.output_bytes * 16,) * 2)

    return apply


def _spawn(argv, cwd, stdin_text, timeout, preexec) -> tuple[int, str, str, bool]:
    """Run one command to completion. Returns (exit_code, stdout, stderr, timed_out).

    `start_new_session` puts the child in its own process group so a timeout kills its
    children too; without it a forking program outlives the request.
    """
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace",
            start_new_session=True, preexec_fn=preexec,
        )
    except OSError as exc:
        raise ExecutorError(f"Could not start {argv[0]!r}: {exc}") from None

    try:
        out, err = proc.communicate(input=stdin_text, timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        out, err = proc.communicate()
        return -1, out or "", err or "", True


class LocalExecutor(Executor):
    name = "local"
    isolation = "rlimit"

    #: Prefixed to every command. Empty here; bubblewrap supplies one below.
    @staticmethod
    def wrap(argv: list[str], workdir: Path) -> list[str]:
        return argv

    @classmethod
    def probe(cls) -> bool:
        return shutil.which("gcc") is not None

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        limits = request.limits
        with tempfile.TemporaryDirectory(prefix="clive-run-") as tmp:
            workdir = Path(tmp)
            for name, contents in request.files.items():
                # The map's keys are authored, never student-supplied, but a traversal
                # here would write anywhere the server can, so it is checked anyway.
                target = (workdir / name).resolve()
                if workdir.resolve() not in target.parents:
                    raise ExecutorError(f"Refusing to write outside the work directory: {name}")
                target.write_text(contents, encoding="utf-8")

            code, _, cerr, timed_out = _spawn(
                self.wrap(request.compile_argv, workdir), workdir,
                None, limits.compile_seconds, None,
            )
            if timed_out:
                return ExecutionResult(False, "Compilation timed out.", "", [])
            if code != 0:
                return ExecutionResult(False, cerr, "", [])

            runs = []
            for stdin_text in request.stdins:
                started = time.monotonic()
                rc, out, err, ran_out = _spawn(
                    self.wrap(request.run_argv, workdir), workdir,
                    stdin_text, limits.run_seconds, _rlimits(limits),
                )
                duration = int((time.monotonic() - started) * 1000)

                truncated = len(out) > limits.output_bytes
                out = out[: limits.output_bytes]

                if ran_out:
                    status = "timeout"
                elif truncated:
                    status = "output_truncated"
                elif rc != 0:
                    status = "runtime_error"
                else:
                    status = "ok"
                runs.append(RunOutcome(status, out, err[: limits.output_bytes], rc, duration))

            return ExecutionResult(True, "", cerr, runs)
```

- [ ] **Step 6: Write `__init__.py`**

Create `src/clive/executors/__init__.py`:

```python
"""Executor registry and resolution.

Mirrors `clive.providers`: one module per backend, a REGISTRY, and an environment
variable that pins a choice. The difference is that a provider is chosen by name and
an executor is chosen by *capability* -- so `get_executor` probes, takes the strongest
backend that actually works on this host, and refuses anything weaker than
CLIVE_SANDBOX_FLOOR.
"""

from __future__ import annotations

from clive import config
from clive.executors.base import (
    ExecutionRequest,
    ExecutionResult,
    Executor,
    ExecutorError,
    Limits,
    RunOutcome,
)
from clive.executors.local import LocalExecutor

__all__ = [
    "ExecutorError", "Executor", "ExecutionRequest", "ExecutionResult",
    "Limits", "RunOutcome", "REGISTRY", "get_executor", "available_executors",
]

#: Strongest first. `get_executor` takes the first one that probes clean.
REGISTRY: list[type[Executor]] = [LocalExecutor]

#: Higher is stronger. CLIVE_SANDBOX_FLOOR names the weakest acceptable value.
ISOLATION_RANK = {"rlimit": 0, "namespace": 1, "container": 2}

_probed: dict[str, bool] = {}


def _probe(cls: type[Executor]) -> bool:
    """Cached, because probing runs a subprocess and the answer cannot change."""
    if cls.name not in _probed:
        try:
            _probed[cls.name] = bool(cls.probe())
        except Exception:
            _probed[cls.name] = False
    return _probed[cls.name]


def available_executors() -> list[type[Executor]]:
    """Every backend that works on this host, strongest first. Used by the tests."""
    return [cls for cls in REGISTRY if _probe(cls)]


def get_executor() -> Executor:
    floor = ISOLATION_RANK.get(config.SANDBOX_FLOOR, 0)

    if config.EXECUTOR:
        chosen = next((c for c in REGISTRY if c.name == config.EXECUTOR), None)
        if chosen is None:
            raise ExecutorError(
                f"Unknown executor {config.EXECUTOR!r}. Set CLIVE_EXECUTOR to one of: "
                f"{', '.join(c.name for c in REGISTRY)}."
            )
        if not _probe(chosen):
            raise ExecutorError(
                f"CLIVE_EXECUTOR names {chosen.name!r}, but it does not work on this host."
            )
        candidates = [chosen]
    else:
        candidates = available_executors()

    for cls in candidates:
        if ISOLATION_RANK[cls.isolation] >= floor:
            return cls()

    if not candidates:
        raise ExecutorError(
            "No usable executor. Install a C compiler, or a container runtime "
            "(podman or docker), to run student code."
        )
    raise ExecutorError(
        f"The strongest available executor is {candidates[0].name!r} with "
        f"{candidates[0].isolation!r} isolation, below CLIVE_SANDBOX_FLOOR="
        f"{config.SANDBOX_FLOOR!r}. Install podman or docker, or lower the floor."
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_executors.py -v`
Expected: 7 passed (parametrised over `local`).

- [ ] **Step 8: Commit**

```bash
git add src/clive/executors/ src/clive/config.py tests/test_executors.py
git commit -m "Add the executor seam and a bare POSIX backend

Files in, one compile plus one run per stdin out, behind a host-wide concurrency
semaphore. This backend reports isolation as 'rlimit' honestly -- it offers no
network or filesystem isolation; CLIVE_SANDBOX_FLOOR is what refuses it."
```

---

### Task 4: bubblewrap isolation

**Files:**
- Modify: `src/clive/executors/local.py` (add `BwrapExecutor`), `src/clive/executors/__init__.py` (register it)
- Test: `tests/test_executors.py` (add two cases)

**Interfaces:**
- Consumes: `LocalExecutor` from Task 3.
- Produces: `executors.local.BwrapExecutor` with `name = "local-bwrap"`, `isolation = "namespace"`. Registered ahead of `LocalExecutor` in `REGISTRY`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executors.py`:

```python
def test_isolation_is_reported_honestly(executor):
    """A backend must not claim isolation it does not provide -- CLIVE_SANDBOX_FLOOR
    is enforced against this string and nothing else."""
    assert executor.isolation in ("container", "namespace", "rlimit")


NETWORK = """
#include <stdio.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <string.h>
int main(void) {
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) { printf("nosocket\\n"); return 0; }
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(80);
    a.sin_addr.s_addr = inet_addr("1.1.1.1");
    printf("%s\\n", connect(s, (struct sockaddr *)&a, sizeof a) == 0 ? "open" : "blocked");
    return 0;
}
"""


def test_isolated_backends_have_no_network(executor):
    if executor.isolation == "rlimit":
        pytest.skip("the bare backend does not claim network isolation")
    result = executor.run(request_for(NETWORK, [""], run_seconds=8))
    assert result.compiled, result.compile_error
    assert result.runs[0].stdout.strip() in ("blocked", "nosocket")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_executors.py -k network -v`
Expected: the network test is skipped, because only `local` is registered and it claims `rlimit`. That skip is the failure — the point of this task is to make a `namespace` backend exist for it to run against.

- [ ] **Step 3: Add `BwrapExecutor` to `local.py`**

Append to `src/clive/executors/local.py`:

```python
#: Bound read-only into the sandbox when they exist. `/usr` covers a merged-usr host on
#: its own; the rest are listed for split-usr distributions, and binding a path that is
#: already a symlink into /usr is harmless.
_SYSTEM_PATHS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin", "/opt")


class BwrapExecutor(LocalExecutor):
    """LocalExecutor with every command wrapped in a bubblewrap sandbox.

    Only `wrap` differs: the compile and the run are identical otherwise, so the two
    backends cannot drift in how they classify a timeout or a crash.
    """

    name = "local-bwrap"
    isolation = "namespace"

    @staticmethod
    def wrap(argv: list[str], workdir: Path) -> list[str]:
        cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
        for path in _SYSTEM_PATHS:
            if os.path.exists(path):
                cmd += ["--ro-bind", path, path]
        cmd += [
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            # Read-write on purpose: gcc writes `program` here and the run step
            # executes it. It is a per-request temp directory, discarded after.
            "--bind", str(workdir), "/work",
            "--chdir", "/work",
            "--",
        ]
        return cmd + argv

    @classmethod
    def probe(cls) -> bool:
        """Run bwrap for real rather than testing for the binary.

        bubblewrap can be installed and still fail: unprivileged user namespaces are
        restricted by AppArmor on Ubuntu 23.10+ and were off by default on older
        Debian. Distributions paper over it by shipping bwrap setuid-root, so the
        only reliable question is whether it works.
        """
        if not super().probe() or shutil.which("bwrap") is None:
            return False
        try:
            done = subprocess.run(
                ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                 "--symlink", "usr/bin", "/bin", "--", "/bin/true"],
                capture_output=True, timeout=10,
            )
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
```

- [ ] **Step 4: Register it ahead of the bare backend**

In `src/clive/executors/__init__.py`, change the import and the registry:

```python
from clive.executors.local import BwrapExecutor, LocalExecutor
```

```python
REGISTRY: list[type[Executor]] = [BwrapExecutor, LocalExecutor]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_executors.py -v`
Expected: 18 passed (9 cases × 2 backends) on a host where bwrap works. On a host where it does not, the `local-bwrap` parameters simply do not appear — confirm with `uv run python -c "from clive.executors import available_executors; print([c.name for c in available_executors()])"`.

- [ ] **Step 6: Commit**

```bash
git add src/clive/executors/ tests/test_executors.py
git commit -m "Add a bubblewrap executor backend

Same compile and run path as the bare backend, wrapped in --unshare-all with a
read-only system and a private /tmp, so a run has no network and cannot write
outside its own work directory. probe() runs bwrap rather than testing for it:
it can be installed and still fail where unprivileged userns is restricted."
```

---

### Task 5: The container backend

The documented default, because the image pins gcc — the only way two participants on two machines get the same verdict for the same code.

**Files:**
- Create: `src/clive/executors/container.py`
- Modify: `src/clive/executors/local.py` (extract the rlimit hook), `src/clive/executors/__init__.py`
- Test: `tests/test_executors.py` (no new cases — the existing nine run against it)

**Interfaces:**
- Consumes: `LocalExecutor`, `Limits`.
- Produces: `executors.container.ContainerExecutor` with `name = "container"`, `isolation = "container"`, class attribute `runtime: str | None` resolved by `probe()`. Registered first in `REGISTRY`.

- [ ] **Step 1: Extract the rlimit hook in `local.py`**

The container's limits are enforced by container flags, and applying an `RLIMIT_AS` of 256 MB to the *podman client* would break the client rather than the student's program. Make the hook overridable.

In `src/clive/executors/local.py`, add a method to `LocalExecutor`:

```python
    @staticmethod
    def preexec_for_run(limits: Limits):
        """Applied in the child between fork and exec. Overridden to None by a backend
        whose limits are enforced somewhere other than this host's process table."""
        return _rlimits(limits)
```

and in `execute`, replace `_rlimits(limits)` in the run loop with `self.preexec_for_run(limits)`.

- [ ] **Step 2: Write `container.py`**

Create `src/clive/executors/container.py`:

```python
"""The container backend: podman or docker, one container per command.

The default when a runtime is present, for one reason -- the image pins gcc. Two
participants on two machines get the same verdict for the same code only if they are
compiling with the same compiler, and this is the only backend that can promise it.

AnimoRank reaches the same place by a different road: Judge0, which is itself
containers, behind an HTTP API. A Judge0 backend would be one more file here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from clive import config
from clive.executors.base import Limits
from clive.executors.local import LocalExecutor


class ContainerExecutor(LocalExecutor):
    name = "container"
    isolation = "container"

    #: Resolved by probe(). podman is preferred: it needs no daemon, so a rootless
    #: install works where docker would need a running service.
    runtime: str | None = None

    @staticmethod
    def preexec_for_run(limits: Limits):
        """None: the limits below are the container's, and applying them to the client
        process instead would cap podman rather than the student's program."""
        return None

    @classmethod
    def wrap_with(cls, argv: list[str], workdir: Path, limits: Limits) -> list[str]:
        return [
            cls.runtime, "run", "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "--memory", f"{limits.memory_mb}m",
            "--pids-limit", str(limits.pids),
            "--cpus", "1",
            # Read-write: gcc writes `program` here and the run step executes it.
            # --read-only still covers the container's own root filesystem.
            "--volume", f"{workdir}:/work:rw",
            "--workdir", "/work",
            # The container stops itself if the client is killed, so a timeout does
            # not leave a container running after the request is gone.
            "--timeout", str(limits.run_seconds + 5),
            config.EXECUTOR_IMAGE,
        ] + argv

    def execute(self, request):
        # `wrap` has no limits argument, so bind them for this call. The base class
        # calls self.wrap(argv, workdir) for both the compile and the run.
        limits = request.limits
        self.wrap = lambda argv, workdir: self.wrap_with(argv, workdir, limits)
        return super().execute(request)

    @classmethod
    def probe(cls) -> bool:
        for runtime in ("podman", "docker"):
            if shutil.which(runtime) is None:
                continue
            try:
                done = subprocess.run(
                    [runtime, "image", "exists", config.EXECUTOR_IMAGE]
                    if runtime == "podman"
                    else [runtime, "image", "inspect", config.EXECUTOR_IMAGE],
                    capture_output=True, timeout=20,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if done.returncode == 0:
                cls.runtime = runtime
                return True
        return False
```

- [ ] **Step 3: Register it first**

In `src/clive/executors/__init__.py`:

```python
from clive.executors.container import ContainerExecutor
from clive.executors.local import BwrapExecutor, LocalExecutor
```

```python
REGISTRY: list[type[Executor]] = [ContainerExecutor, BwrapExecutor, LocalExecutor]
```

- [ ] **Step 4: Pull the image and run the suite against it**

```bash
podman pull docker.io/library/gcc:14
uv run pytest tests/test_executors.py -v
```

Expected: the nine cases now also run with id `container`. `probe()` deliberately returns False when the image is absent rather than pulling ~1.3 GB inside a test, so without the pull the container parameters simply do not appear.

- [ ] **Step 5: Confirm the floor works**

```bash
CLIVE_SANDBOX_FLOOR=container uv run python -c "from clive.executors import get_executor; print(get_executor().name)"
```
Expected: `container` if the image is pulled, otherwise an `ExecutorError` naming the floor. Then:
```bash
CLIVE_EXECUTOR=local CLIVE_SANDBOX_FLOOR=container uv run python -c "from clive.executors import get_executor; get_executor()"
```
Expected: `ExecutorError` — a pinned weak backend must not bypass the floor.

- [ ] **Step 6: Commit**

```bash
git add src/clive/executors/ tests/test_executors.py
git commit -m "Add a container executor backend, preferred when present

podman or docker, one container per command, with the image pinning gcc so the
same code earns the same verdict on any host. Its limits are container flags,
so the rlimit hook is overridden to None -- applying RLIMIT_AS to the podman
client would cap the client rather than the student's program."
```

---

### Task 6: `grade.py`

**Files:**
- Create: `src/clive/grade.py`
- Test: `tests/test_grade.py` (create)

**Interfaces:**
- Consumes: `executors.get_executor`, `ExecutionRequest`, `Limits`, `ExecutionResult`, `RunOutcome`.
- Produces:
  - `grade.normalise(text: str) -> str`
  - `grade.COMPILE_ARGV`, `grade.RUN_ARGV`
  - `grade.grade(problem: dict, code: str, scope: str = "public", executor=None) -> dict` returning the shape in the spec.

- [ ] **Step 1: Write the failing test**

Create `tests/test_grade.py`:

```python
"""Grading: comparison semantics, scope, and the hidden-case rule.

No subprocess and no network -- a stub executor returns canned runs, because what is
under test is the comparison and the stripping, not the compiler.
"""

from __future__ import annotations

import pytest

from clive import grade
from clive.executors.base import ExecutionResult, RunOutcome


class StubExecutor:
    """Returns one canned RunOutcome per stdin, in order."""

    name, isolation = "stub", "container"

    def __init__(self, stdouts, compiled=True, compile_error="", warnings=""):
        self.stdouts, self.compiled = stdouts, compiled
        self.compile_error, self.warnings = compile_error, warnings
        self.seen = None

    def run(self, request):
        self.seen = request
        if not self.compiled:
            return ExecutionResult(False, self.compile_error, "", [])
        runs = [RunOutcome("ok", s, "", 0, 1) for s in self.stdouts]
        return ExecutionResult(True, "", self.warnings, runs)


PROBLEM = {
    "slug": "demo",
    "public_test_cases": [{"input": "a", "output": "1"}, {"input": "b", "output": "2"}],
    "hidden_test_cases": [{"input": "c", "output": "3"}],
}


def test_trailing_newline_does_not_fail_a_correct_program():
    """The load-bearing divergence from AnimoRank. Every problem in the corpus stores
    its expected output without a trailing newline, and every correct C program that
    uses printf("%d\\n", ...) emits one."""
    result = grade.grade(PROBLEM, "code", "public", StubExecutor(["1\n", "2\n"]))
    assert result["passed"]
    assert result["counts"] == {"passed": 2, "failed": 0, "total": 2}


def test_interior_whitespace_still_matters():
    problem = {"public_test_cases": [{"input": "", "output": "1 2"}], "hidden_test_cases": []}
    assert not grade.grade(problem, "code", "public", StubExecutor(["1  2\n"]))["passed"]


def test_trailing_blank_lines_are_ignored():
    problem = {"public_test_cases": [{"input": "", "output": "1"}], "hidden_test_cases": []}
    assert grade.grade(problem, "code", "public", StubExecutor(["1\n\n\n"]))["passed"]


def test_public_scope_does_not_run_hidden_cases():
    stub = StubExecutor(["1\n", "2\n"])
    grade.grade(PROBLEM, "code", "public", stub)
    assert stub.seen.stdins == ["a", "b"]


def test_all_scope_runs_every_case():
    stub = StubExecutor(["1\n", "2\n", "3\n"])
    result = grade.grade(PROBLEM, "code", "all", stub)
    assert stub.seen.stdins == ["a", "b", "c"]
    assert result["counts"]["total"] == 3


def test_hidden_cases_never_carry_their_io():
    stub = StubExecutor(["1\n", "2\n", "WRONG\n"])
    result = grade.grade(PROBLEM, "code", "all", stub)
    hidden = [c for c in result["cases"] if c["hidden"]]
    assert len(hidden) == 1
    assert not hidden[0]["passed"]
    assert set(hidden[0]) == {"hidden", "passed", "status"}
    assert "3" not in str(hidden[0])


def test_public_cases_carry_their_io():
    result = grade.grade(PROBLEM, "code", "public", StubExecutor(["1\n", "NOPE\n"]))
    second = result["cases"][1]
    assert second["input"] == "b"
    assert second["expected"] == "2"
    assert second["actual"] == "NOPE\n"
    assert not second["passed"]


def test_compile_failure_reports_no_cases():
    stub = StubExecutor([], compiled=False, compile_error="main.c:1: error: expected ';'")
    result = grade.grade(PROBLEM, "code", "all", stub)
    assert not result["compiled"]
    assert not result["passed"]
    assert result["cases"] == []
    assert "expected ';'" in result["compile_error"]


def test_warnings_are_carried_without_failing():
    stub = StubExecutor(["1\n", "2\n"], warnings="main.c:3: warning: unused variable")
    result = grade.grade(PROBLEM, "code", "public", stub)
    assert result["passed"]
    assert "unused variable" in result["warnings"]


def test_a_timeout_is_a_failed_case_not_an_exception():
    class Timeouts(StubExecutor):
        def run(self, request):
            return ExecutionResult(True, "", "", [RunOutcome("timeout", "", "", -1, 5000)] * 2)

    result = grade.grade(PROBLEM, "code", "public", Timeouts([]))
    assert not result["passed"]
    assert result["cases"][0]["status"] == "timeout"


def test_the_student_code_is_written_as_main_c():
    stub = StubExecutor(["1\n", "2\n"])
    grade.grade(PROBLEM, "int main(void){}", "public", stub)
    assert stub.seen.files == {"main.c": "int main(void){}"}


def test_unknown_scope_is_refused():
    with pytest.raises(ValueError):
        grade.grade(PROBLEM, "code", "everything", StubExecutor([]))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_grade.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clive.grade'`.

- [ ] **Step 3: Write `grade.py`**

Create `src/clive/grade.py`:

```python
"""Grading one C submission against a problem's test cases.

The seam between a problem and an executor, and deliberately pure: plain data in,
plain data out, no filesystem and no HTTP -- so the Studio's sandbox grades a scratch
problem exactly as /student grades a saved one. That is the same property `judge()`
has, and for the same reason.

Two rules live here rather than in the caller:

  Hidden cases are stripped of everything but a pass/fail before they are returned.
  AnimoRank does this in its route (src/routes/api/practice-session/[id]/run), which
  is one forgetful caller away from a leak. Below the route, no caller can forget.

  Comparison normalises trailing whitespace. AnimoRank compares stdout strictly, and
  every problem in cases/problems/ stores its expected output without a trailing
  newline -- so a strict comparison would reject correct programs on all nine of
  them. Interior whitespace is still significant.
"""

from __future__ import annotations

from typing import Literal

from clive.executors import ExecutionRequest, Limits, get_executor

__all__ = ["COMPILE_ARGV", "RUN_ARGV", "SCOPES", "normalise", "grade"]

#: AnimoRank's compile line, verbatim, from
#: src/lib/testCase/testCase/programIOTestCase/compile.sh -- including -Werror, which
#: means an unused variable is a failed build. Kept for parity; `warnings` on the
#: result is what lets the page show a warning as its own state rather than as a
#: wrong answer.
COMPILE_ARGV = ["gcc", "-Werror", "-Wall", "-o", "program", "main.c", "-lm", "-lpthread"]

RUN_ARGV = ["./program"]

SCOPES = ("public", "all")


def normalise(text: str) -> str:
    """Trailing whitespace per line, then trailing blank lines. Nothing else."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def grade(
    problem: dict,
    code: str,
    scope: Literal["public", "all"] = "public",
    executor=None,
) -> dict:
    """Compile `code` once and run it against `problem`'s cases in `scope`.

    `executor` is injectable so the tests can supply canned runs; production passes
    nothing and gets whatever `get_executor` resolves for this host.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}; expected one of {', '.join(SCOPES)}.")

    public = list(problem.get("public_test_cases") or [])
    hidden = list(problem.get("hidden_test_cases") or []) if scope == "all" else []
    cases = [(c, False) for c in public] + [(c, True) for c in hidden]

    executor = executor or get_executor()
    result = executor.run(
        ExecutionRequest(
            files={"main.c": code},
            compile_argv=COMPILE_ARGV,
            run_argv=RUN_ARGV,
            stdins=[str(c.get("input", "")) for c, _ in cases],
            limits=Limits(),
        )
    )

    out = {
        "compiled": result.compiled,
        "compile_error": result.compile_error,
        "warnings": result.warnings,
        "passed": False,
        "counts": {"passed": 0, "failed": 0, "total": len(cases)},
        "cases": [],
        "executor": {"name": executor.name, "isolation": executor.isolation},
    }
    if not result.compiled:
        # Nothing ran, so there are no cases to report. `total` stays at the number
        # the student would have faced, which is what the page counts against.
        return out

    for (case, is_hidden), run in zip(cases, result.runs):
        expected = str(case.get("output", ""))
        ok = run.status == "ok" and normalise(run.stdout) == normalise(expected)
        out["counts"]["passed" if ok else "failed"] += 1

        if is_hidden:
            # Everything else about a hidden case stays on the server.
            out["cases"].append({"hidden": True, "passed": ok, "status": run.status})
        else:
            out["cases"].append(
                {
                    "hidden": False,
                    "passed": ok,
                    "status": run.status,
                    "input": str(case.get("input", "")),
                    "expected": expected,
                    "actual": run.stdout,
                    "stderr": run.stderr,
                    "duration_ms": run.duration_ms,
                }
            )

    out["passed"] = out["counts"]["failed"] == 0 and bool(cases)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grade.py -v`
Expected: 12 passed.

- [ ] **Step 5: Grade a real program end to end**

```bash
uv run python -c "
from clive import grade, prompts
p = prompts.load_problem('count_vowels')
src = open('/dev/stdin').read()
print(grade.grade(p, src, 'public')['counts'])
" <<'C'
#include <stdio.h>
#include <string.h>
int main(void) {
    char line[256];
    if (!fgets(line, sizeof line, stdin)) return 1;
    int n = 0;
    for (size_t i = 0; i < strlen(line); i++) {
        char c = line[i] | 32;
        if (c=='a'||c=='e'||c=='i'||c=='o'||c=='u') n++;
    }
    printf("%d\n", n);
    return 0;
}
C
```
Expected: `{'passed': 3, 'failed': 0, 'total': 3}`. This is the check that the trailing-newline rule actually works against the real corpus — a strict comparison prints `{'passed': 0, 'failed': 3, ...}`.

- [ ] **Step 6: Commit**

```bash
git add src/clive/grade.py tests/test_grade.py
git commit -m "Add grade.py: one submission against a problem's test cases

Pure data in, pure data out, so the sandbox grades a scratch problem exactly as
/student grades a saved one. Hidden cases are stripped to a bare pass/fail here
rather than in the route, so no caller can forget to. Comparison normalises
trailing whitespace: a strict port of AnimoRank's rule rejects correct programs
on all nine problems in the corpus, because none stores a trailing newline."
```

---

### Task 7: The Implement phase content

Authored YAML only — no Python. The phase is inert until Task 9 teaches `submit` to read `gate`, so this task is safe to land on its own.

**Files:**
- Create: `prompts/phases/implement.yaml`, `criteria/implement.yaml`
- Modify: `cases/problems/count_vowels.yaml`, `cases/problems/crowley_path.yaml`
- Test: `tests/test_implement_content.py` (create)

**Interfaces:**
- Consumes: `gate` and `kind` from Task 1; `starter_code` from Task 2.
- Produces: a phase with `phase: implement`, `order: 4`, `gate: tests`, and one artifact field `id: code`. Criteria ids: `follows_own_design`, `state_matches_design`, `handles_own_edge_cases`, `readable` — all `gate: advisory`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_implement_content.py`:

```python
"""The Implement phase's authored content, and the one rule it must never break.

`student.submit` treats a tests-gated phase as passed the moment every case passes.
A gating criterion in criteria/implement.yaml would let the judge block code that
demonstrably works, which the design rules out -- so it is pinned here rather than
left as a convention someone edits away.
"""

from __future__ import annotations

from clive import prompts


def test_implement_is_the_fourth_phase():
    phases = prompts.list_phases()
    assert [p["phase"] for p in phases][-1] == "implement"
    assert phases[-1]["order"] == 4


def test_implement_is_gated_by_tests():
    assert prompts.load_phase("implement")["gate"] == "tests"


def test_implement_submits_one_code_field():
    fields = prompts.load_phase("implement")["artifact_fields"]
    assert len(fields) == 1
    assert fields[0]["id"] == "code"
    assert fields[0]["kind"] == "code"
    assert fields[0]["language"] == "c"


def test_every_implement_criterion_is_advisory():
    criteria = prompts.load_criteria("implement")["criteria"]
    assert criteria, "the phase needs criteria for the advisory review to say anything"
    offenders = [c["id"] for c in criteria if c["gate"] != "advisory"]
    assert not offenders, (
        f"{offenders} would let the judge block code that passes every test. "
        "Implement is gated by the compiler; its criteria advise and never bar."
    )


def test_the_template_renders_with_a_code_artifact():
    phase = prompts.load_phase("implement")
    rendered = prompts.render_user_prompt(
        phase,
        prompts.load_problem("count_vowels"),
        {"code": "int main(void) { return 0; }"},
        prompts.load_criteria("implement")["criteria"],
        attempt=1,
        prior_artifacts=[{"label": "Design", "fields": [{"label": "Steps", "value": "1. Read"}]}],
    )
    assert "int main(void) { return 0; }" in rendered
    assert "1. Read" in rendered


def test_problems_with_starter_code_start_from_a_compilable_skeleton():
    for slug in ("count_vowels", "crowley_path"):
        starter = prompts.load_problem(slug)["starter_code"]
        assert "#include <stdio.h>" in starter
        assert "int main(void)" in starter
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_implement_content.py -v`
Expected: FAIL — `ContentError: No such file: .../prompts/phases/implement.yaml`.

- [ ] **Step 3: Write `prompts/phases/implement.yaml`**

```yaml
# The "I" of PCDIT, and the first phase whose gate is not a judge.
#
# The compiler decides whether this phase passes: every test case must pass. The model
# never gets a vote on that, and it is only called at all once the code already works --
# so its whole job is the question a compiler cannot answer, which is whether the code
# the student wrote is the design the student planned.
#
# Notes live in this leading block because only the leading block survives a save from
# CLive Studio (`read_header` in prompts.py).
#
#   gate       `tests`. See docs/superpowers/specs/2026-09-07-implement-phase-design.md.
#              student.submit grades before it judges, and does not judge at all when a
#              case fails -- there is no point spending a call reviewing broken code, and
#              it means the review below always reads a working program.
#
#   criteria   All advisory, and `tests/test_implement_content.py` enforces it. A gating
#              criterion here would let the judge bar code that passes every test.
#
#   evidence   Inverted from the other three phases in one respect. There, EARLIER PHASES
#              is context that must never be quoted. Here the earlier phases are the
#              standard being applied -- the criteria are *about* conformance to them --
#              so the design may be described and referred to. Evidence is still a span
#              of the student's code, because that is the artifact being judged.

id: phase.implement
version: 1
phase: implement
label: Implement
order: 4
gate: tests
created: 2026-09-07
changelog: >
  v1: Initial definition. The fourth PCDIT step, gated by the test cases and advised by
  a judge that reads the code against the student's own Problem, Cases and Design. Only
  runs once every test passes, so it never comments on correctness -- the compiler has
  already settled that.

model:
  id: deepseek-v4-pro
  effort: medium
  thinking: adaptive
  max_output_tokens: 8000
  response_format: json_schema
  schema: base/output_schema.json

task_description: |
  Write the C program that carries out the plan you designed. Read from standard input and
  print to standard output, exactly in the format the problem asks for -- nothing else, no
  prompts like "Enter a number:".

  Run checks your program against the examples you were given, as often as you like and at
  no cost. Submit runs it against those and against cases you have not seen.

  Your program has to compile with warnings treated as errors, so an unused variable will
  stop the build. Once every case passes, your code is read once more against the plan you
  wrote in Design -- not to find bugs, but to say where the program and the plan disagree.

artifact_fields:
  - id: code
    label: Your C program
    kind: code
    language: c
    hint: A complete program. Read from standard input, print to standard output.
    rows: 20

system_prompt: |
  You are reviewing one student's C program at the last step of a structured problem-solving process. You are not holding a conversation, and you are not teaching C.

  The program has already passed every test case. Its correctness is settled and is not yours to re-litigate. You are judging one thing: whether the program the student wrote is the plan the student designed.

  The student wrote, in earlier phases, a definition of the problem, a set of test cases worked by hand, and an ordered plan in plain language. Those are supplied under EARLIER PHASES. They are the standard you apply.

  You judge the artifact against a fixed list of criteria. For each criterion you return exactly one verdict.

  Rules:
  - Return exactly one verdict per criterion id listed under CRITERIA TO JUDGE. Never merge, skip, split, or invent a criterion id.
  - Judge each criterion only against its own stated text and guidance. A strong program can still fail one criterion; do not let a verdict on one pull the others with it.
  - Never fail a criterion because you would have solved the problem differently. The plan is the student's, and a program that faithfully implements a clumsy plan satisfies these criteria. Elegance is not being judged, and neither is efficiency.
  - Do not report bugs. Every test passed. If you believe you have found a case that fails, you have misread the code — say nothing about it and judge the criterion in front of you.
  - Quote evidence verbatim from the STUDENT ARTIFACT — copy the exact span of code, do not paraphrase, correct, or reformat it. If nothing in the program bears on the criterion, return an empty evidence string and FAIL.
  - EARLIER PHASES is the standard, not the evidence. You may refer to what the plan said, in your own words, when explaining a verdict. The evidence string itself must always be a span of the student's code.
  - The problem statement and public test cases are context. Never quote them as evidence.
  - Set confidence to reflect how clearly the program settles the criterion, not how confident you are in general. Use "low" when the correspondence is arguable.

user_template: |
  PROBLEM STATEMENT
  {{ problem.statement }}

  {% if problem.public_test_cases %}
  PUBLIC TEST CASES
  {% for case in problem.public_test_cases %}
  - input: {{ case.input | tojson }} output: {{ case.output | tojson }}
  {% endfor %}
  {% endif %}
  {% if prior_artifacts %}
  EARLIER PHASES
  This student's own work from earlier phases. This is the standard you are applying: the
  criteria ask whether the program below matches it. Refer to it in your reasoning; never
  use it as the evidence string.
  {% for p in prior_artifacts %}
  {{ p.label }}:
  {% for f in p.fields %}
  - {{ f.label }}: {{ f.value }}
  {% endfor %}
  {% endfor %}
  {% endif %}

  STUDENT ARTIFACT
  This program compiles and passes every test case.
  {% for f in artifact_fields %}

  {{ f.label }}:
  {{ artifact[f.id] | default("(not provided)", true) }}
  {% endfor %}

  CRITERIA TO JUDGE
  Return exactly one verdict for each of the following {{ criteria_to_judge | length }} criteria, using the id in brackets.
  {% for c in criteria_to_judge %}
  - [{{ c.id }}] {{ c.text }}
    {{ c.guidance | trim | indent(2) }}
  {% endfor %}
```

- [ ] **Step 4: Write `criteria/implement.yaml`**

```yaml
# Criteria for phase.implement (the "I" of PCDIT).
#
# Every criterion here is `advisory`, and tests/test_implement_content.py fails the suite
# if one is not. This phase is gated by the compiler: the tests decide whether the student
# advances, and these criteria are the review that happens afterwards. A `gating` entry
# would let the judge hold a student on code that passes every case.
#
# They are also all *comparative*. The question is never "is this good C" in the abstract,
# it is "is this the program the student planned" -- which is the only question that needs
# the earlier phases, and the only one a plain autograder cannot ask.

id: criteria.implement
phase: implement
version: 1

criteria:
  - id: follows_own_design
    text: The program carries out the steps of the student's own Design, in that order.
    gate: advisory
    guidance: |
      PASS if a reader holding the Design beside the code can match the plan's steps onto
      the program -- the same work happening in the same order. Extra code the plan did
      not mention is fine when it serves a step (reading input, printing the result).
      FAIL if the program reaches the right answer by a route the plan does not describe:
      a different traversal, a different decomposition, a step the plan required that the
      code does not perform. Do not fail this because the code is more detailed than the
      plan -- a plan is meant to be less specific than the program.

  - id: state_matches_design
    text: The variables correspond to the state the student said the algorithm keeps.
    gate: advisory
    guidance: |
      PASS if each thing the Design named as state -- a counter, a total, a flag, an array
      -- exists in the program, and the program does not silently depend on state the plan
      never mentioned. Names need not match; roles must.
      FAIL if a named piece of state is absent, or if the program carries something between
      iterations that the plan does not account for. A loop index or a scratch variable
      local to one step is not state and does not fail this.

  - id: handles_own_edge_cases
    text: The edge cases the student invented in Cases are handled deliberately.
    gate: advisory
    guidance: |
      PASS if, for each edge case the student wrote in the Cases phase, the code contains
      something that addresses it -- a guard, a branch, an initialisation, or a loop
      structure that plainly covers it.
      FAIL if an edge case the student themselves identified works only by accident, with
      nothing in the program written for it. Say which case. If the Cases phase named no
      edge cases, FAIL with an empty evidence string: the gap is real and worth reporting,
      even though it is not this phase's doing.

  - id: readable
    text: The program can be followed by a person reading it once.
    gate: advisory
    guidance: |
      PASS if names say what they hold, the structure is flat enough to follow, and a
      reader does not have to simulate the program to understand it.
      FAIL only for something a reader would genuinely stumble on: single-letter names for
      values that carry meaning, a condition compounded past the point of reading, repeated
      blocks that obscure what differs. Do not fail this for formatting, brace style,
      comment density, or any preference a linter would settle.
```

- [ ] **Step 5: Add starter code to two problems**

Append to `cases/problems/count_vowels.yaml`:

```yaml
starter_code: |
  #include <stdio.h>
  #include <string.h>

  int main(void) {
      char line[128];
      if (fgets(line, sizeof line, stdin) == NULL) {
          return 1;
      }

      /* Count the vowels in `line`, then print the count. */

      return 0;
  }
```

Append to `cases/problems/crowley_path.yaml`:

```yaml
starter_code: |
  #include <stdio.h>
  #include <string.h>

  /* Return 1 if Crowley can reach the end of the path, 0 if he cannot. */
  int solvePath(const char *path) {
      return 0;
  }

  int main(void) {
      char path[16];
      if (scanf("%15s", path) != 1) {
          return 1;
      }
      printf("%d\n", solvePath(path));
      return 0;
  }
```

This is how the function-shaped problem is served without porting AnimoRank's `FunctionOutputTestCase`: the harness the student would otherwise have to guess at is given to them, and the test cases stay plain stdin/stdout pairs.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_implement_content.py -v`
Expected: 6 passed.

- [ ] **Step 7: Verify the starter code compiles**

```bash
uv run python -c "
from clive import grade, prompts
for slug in ('count_vowels', 'crowley_path'):
    p = prompts.load_problem(slug)
    r = grade.grade(p, p['starter_code'], 'public')
    print(slug, 'compiled:', r['compiled'], r['compile_error'][:200])
"
```
Expected: `compiled: True` for both. Starter code that does not compile is worse than none — with `-Werror` a student's first Run would fail before they wrote anything. It should compile and produce wrong answers, not fail to build.

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest`
Expected: green. `tests/test_student.py` iterates every phase in the repo, so the new criteria are now covered by the existing rubric-leak assertions automatically — confirm it still passes.

- [ ] **Step 9: Commit**

```bash
git add prompts/phases/implement.yaml criteria/implement.yaml cases/problems/ tests/test_implement_content.py
git commit -m "Add the Implement phase content

A fourth phase gated by tests, whose criteria are all advisory and all
comparative: they ask whether the program is the plan the student designed,
which is the only question needing the earlier phases and the only one a plain
autograder cannot ask. crowley_path's solvePath() harness ships as starter_code
rather than porting AnimoRank's FunctionOutputTestCase codegen."
```

---

### Task 8: The nudge for failing code

**Files:**
- Create: `prompts/base/nudge_code.yaml`
- Modify: `src/clive/prompts.py` (`load_nudge_code`, `render_nudge_code_prompt`), `src/clive/nudge.py` (`nudge_code`)
- Test: `tests/test_nudge_code.py` (create)

**Interfaces:**
- Consumes: `Nudge` pydantic model from `clive.nudge`; `get_provider`.
- Produces:
  - `prompts.load_nudge_code() -> dict`
  - `prompts.render_nudge_code_prompt(doc, phase, problem, code, failures, compile_error, hidden_failed, attempt, prior_artifacts) -> str`
  - `nudge.nudge_code(phase, problem, code, test_run, attempt=1, prior_artifacts=None) -> dict` returning `{"summary", "focus_id", "reason", "nudge", "failing"}` — the same keys `nudge()` returns, so the page renders both through one component. `failing` is a list of `{"id", "text"}` where `id` is the string index of a failing public case (or `"compile"`) and `text` is a one-line description.

- [ ] **Step 1: Write the failing test**

Create `tests/test_nudge_code.py`:

```python
"""The code nudge: what it may see, and what it must never see.

The hidden-case rule is the whole point of these tests. A nudge prompt is the one place
a hidden input could leak without any route returning it, because the model is handed
the failures directly.
"""

from __future__ import annotations

import pytest

from clive import nudge as nudging
from clive import prompts

PHASE = "implement"

TEST_RUN = {
    "compiled": True,
    "compile_error": "",
    "warnings": "",
    "passed": False,
    "counts": {"passed": 1, "failed": 2, "total": 3},
    "cases": [
        {"hidden": False, "passed": True, "status": "ok",
         "input": "Hello World", "expected": "3", "actual": "3\n"},
        {"hidden": False, "passed": False, "status": "ok",
         "input": "rhythm", "expected": "0", "actual": "1\n"},
        {"hidden": True, "passed": False, "status": "ok"},
    ],
}


class StubProvider:
    name, api_key_env, default_model = "stub", "STUB_KEY", "stub-1"
    model_choices = ["stub-1"]

    def __init__(self):
        self.user_prompt = None

    def has_api_key(self):
        return True

    def judge_json(self, system, user, model, max_output_tokens, effort, schema):
        self.user_prompt = user
        parsed = schema(summary="One case disagrees.", focus_id="1",
                        reason="It is the simplest.", nudge="What does y count as?")
        return type("R", (), {"parsed": parsed, "model": "stub-1",
                              "input_tokens": 1, "output_tokens": 1})()


@pytest.fixture
def stub(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr(nudging, "get_provider", lambda *a, **k: provider)
    return provider


def run_nudge(stub, test_run=None, code="int main(void){}"):
    return nudging.nudge_code(
        prompts.load_phase(PHASE),
        prompts.load_problem("count_vowels"),
        code,
        test_run or TEST_RUN,
        attempt=2,
        prior_artifacts=[{"label": "Design", "fields": [{"label": "Steps", "value": "1. Read"}]}],
    )


def test_returns_the_same_keys_as_the_criterion_nudge(stub):
    result = run_nudge(stub)
    assert set(result) == {"summary", "focus_id", "reason", "nudge", "failing"}


def test_only_failing_cases_are_listed(stub):
    result = run_nudge(stub)
    assert [f["id"] for f in result["failing"]] == ["1", "hidden"]


def test_the_prompt_sees_failing_public_io(stub):
    run_nudge(stub)
    assert "rhythm" in stub.user_prompt
    assert "1\n" in stub.user_prompt or "1" in stub.user_prompt


def test_the_prompt_never_sees_a_hidden_input(stub):
    """The rule that matters. A hidden case reaches the model as a count, never as I/O."""
    hidden_secret = "SECRET_HIDDEN_INPUT"
    test_run = dict(TEST_RUN)
    test_run["cases"] = TEST_RUN["cases"][:2] + [
        {"hidden": True, "passed": False, "status": "ok",
         "input": hidden_secret, "expected": "99", "actual": "0"},
    ]
    run_nudge(stub, test_run)
    assert hidden_secret not in stub.user_prompt
    assert "99" not in stub.user_prompt


def test_the_prompt_carries_the_students_design(stub):
    run_nudge(stub)
    assert "1. Read" in stub.user_prompt


def test_a_compile_error_is_nudged_on_instead_of_cases(stub):
    test_run = {
        "compiled": False, "compile_error": "main.c:4:5: error: expected ';'",
        "warnings": "", "passed": False,
        "counts": {"passed": 0, "failed": 0, "total": 3}, "cases": [],
    }
    result = run_nudge(stub, test_run)
    assert [f["id"] for f in result["failing"]] == ["compile"]
    assert "expected ';'" in stub.user_prompt


def test_nothing_failing_is_refused(stub):
    passing = {"compiled": True, "compile_error": "", "warnings": "", "passed": True,
               "counts": {"passed": 3, "failed": 0, "total": 3}, "cases": []}
    with pytest.raises(nudging.JudgeError):
        run_nudge(stub, passing)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_nudge_code.py -v`
Expected: FAIL — `AttributeError: module 'clive.nudge' has no attribute 'nudge_code'`.

- [ ] **Step 3: Write `prompts/base/nudge_code.yaml`**

```yaml
# The code nudge: one submission whose tests did not pass, one thing to look at next.
#
# Sibling of base/nudge.yaml and deliberately a separate document. That one runs on a judge
# result and names a failing gating criterion; this one runs on a compiler result and names
# a failing test case. `nudge()` refuses to run without failing gates, and a tests-gated
# phase has none -- every criterion it owns is advisory.
#
# Notes live in this leading block because only the leading block survives a save from
# CLive Studio (`read_header` in prompts.py).
#
#   hidden cases
#              The model is told how many hidden cases failed and nothing else. Never their
#              input, expected output, or actual output. tests/test_nudge_code.py asserts
#              this against the rendered prompt, because this is the one place a hidden
#              input could reach a student without any route ever returning it.
#
#   the design The student's own Design is supplied and is the thing that makes this nudge
#              worth a model call. A diff between expected and actual is something the page
#              already shows. What it cannot show is where the program stopped following
#              the plan, and that is what this prompt asks for.
#
#   name, never fill
#              Shared doctrine with base/nudge.yaml and base/hint.yaml. Say where the gap
#              is; never write the line that closes it.

id: base.nudge_code
version: 1
created: 2026-09-07
changelog: >
  v1: First version. Runs when a tests-gated submission fails to compile or fails a case.
  Acknowledges every failure in one summary, picks one to look at first, and points at the
  disagreement between the program and the student's own design rather than at the diff.

model:
  # No `id`, for the reason base/nudge.yaml gives: this document is shared, and a pinned
  # id is provider-specific. No `schema` either: like base/nudge.yaml, this prompt's
  # output contract is the `Nudge` pydantic model the provider is handed directly.
  effort: medium
  max_output_tokens: 2000

system_prompt: |
  You are helping one student whose C program does not yet pass its tests. You are not holding a conversation, and you are not writing their code.

  You are given the program, the cases it failed, and the plan the student wrote in plain language before they started coding. Your job is to point at one place where the program and the plan disagree, or where the program does something the plan never said to do.

  Rules:
  - Never write code, and never give a line the student can paste. Not a corrected condition, not a loop header, not an initialiser. Naming the variable that is wrong is allowed; saying what to set it to is not.
  - Prefer a discrepancy with the student's own plan over a bare description of the bug. "Your plan resets the counter each time round; the program sets it once, before the loop" teaches something. "You have an off-by-one" does not.
  - Point at exactly one thing. A student handed four corrections patches all four shallowly.
  - Use the failing case as evidence for where to look, not as the subject. The student can already see which case failed and what it printed.
  - If the program did not compile, the compiler error is the only thing that matters. Say what the compiler is objecting to in plain language. Remember that warnings are errors here, so an unused variable stops the build and is worth naming as exactly that rather than as a mistake in their logic.
  - Never mention a hidden test case's input or expected output. You are not given them, and you must not guess at them or invent one to illustrate a point.
  - Write to the student, in the second person, in plain language. No headings, no lists, no code fences.

  Return:
  - summary: two or three sentences accounting for everything that failed, so the student sees the whole gap at once.
  - focus_id: the id of the one failure to look at first, copied verbatim from the bracketed id in WHAT FAILED.
  - reason: one sentence on why that one first.
  - nudge: the nudge itself. Names where the gap is; never fills it.

user_template: |
  PROBLEM STATEMENT
  {{ problem.statement }}

  {% if prior_artifacts %}
  WHAT THIS STUDENT PLANNED
  Their own work from the earlier phases. This is what the program is supposed to be.
  {% for p in prior_artifacts %}
  {{ p.label }}:
  {% for f in p.fields %}
  - {{ f.label }}: {{ f.value }}
  {% endfor %}
  {% endfor %}
  {% endif %}

  THEIR PROGRAM
  {{ code }}

  WHAT FAILED
  {% if compile_error %}
  - [compile] The program did not compile. Warnings are errors here.
  {{ compile_error | trim | indent(2) }}
  {% else %}
  {% for f in failures %}
  - [{{ f.id }}] input {{ f.input | tojson }} — expected {{ f.expected | tojson }}, printed {{ f.actual | tojson }}{% if f.status != "ok" %} ({{ f.status }}){% endif %}

  {% endfor %}
  {% if hidden_failed %}
  - [hidden] {{ hidden_failed }} case{{ "s" if hidden_failed > 1 else "" }} the student has not seen also failed. You are not told what they contain, and must not speculate about them.
  {% endif %}
  {% endif %}

  This is attempt {{ attempt }}.
```

- [ ] **Step 4: Add the loader and renderer to `prompts.py`**

After `load_nudge`, add:

```python
def nudge_code_path() -> Path:
    return BASE_PROMPTS_DIR / "nudge_code.yaml"


def load_nudge_code() -> dict:
    """The nudge for a tests-gated phase.

    Separate from `load_nudge` because the two prompts take different inputs: that one
    is handed failing criteria, this one is handed failing test cases and a compiler.
    """
    path = nudge_code_path()
    if not path.exists():
        raise ContentError(
            "The code nudge prompt is missing. Expected prompts/base/nudge_code.yaml."
        )
    data = read_yaml(path)
    for key in ("system_prompt", "user_template"):
        if not str(data.get(key, "")).strip():
            raise ContentError(f"prompts/base/nudge_code.yaml has no {key}.")
    model = data.setdefault("model", {})
    model.setdefault("id", get_provider().default_model)
    model.setdefault("effort", "medium")
    model.setdefault("max_output_tokens", 2000)
    return data


def render_nudge_code_prompt(
    doc: dict,
    phase: dict,
    problem: dict,
    code: str,
    failures: list[dict],
    compile_error: str = "",
    hidden_failed: int = 0,
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
) -> str:
    """Render the code-nudge template.

    `failures` carries only public cases -- the caller selects them, and
    `tests/test_nudge_code.py` asserts a hidden input never reaches the rendered
    string. `hidden_failed` is a count and must stay a count.
    """
    template = jinja_env().from_string(doc["user_template"])
    return template.render(
        phase=phase,
        problem=problem,
        code=code or "",
        failures=failures,
        compile_error=compile_error or "",
        hidden_failed=hidden_failed,
        attempt=attempt,
        prior_artifacts=prior_artifacts or [],
    )
```

- [ ] **Step 5: Add `nudge_code` to `nudge.py`**

Append to `src/clive/nudge.py`, and add `"nudge_code"` to `__all__`:

```python
def nudge_code(
    phase: dict,
    problem: dict,
    code: str,
    test_run: dict,
    attempt: int = 1,
    prior_artifacts: list[dict] | None = None,
) -> dict:
    """Ask for one nudge about one submission whose tests did not pass.

    The counterpart to `nudge()` for a tests-gated phase. That one selects failing
    gating criteria; this one selects failing test cases -- and, exactly as there, the
    selection happens here rather than in the caller, so no caller can hand the model a
    hidden case's input. The model is told how many hidden cases failed and nothing more.

    `failing` is returned computed rather than taken from the reply, for the reason
    `nudge()` gives: a summary that forgets a failure must not be able to hide it.
    """
    compile_error = "" if test_run.get("compiled", True) else test_run.get("compile_error", "")

    public_failures = [
        {
            "id": str(i),
            "input": c.get("input", ""),
            "expected": c.get("expected", ""),
            "actual": c.get("actual", ""),
            "status": c.get("status", "ok"),
        }
        for i, c in enumerate(test_run.get("cases") or [])
        if not c.get("hidden") and not c.get("passed")
    ]
    hidden_failed = sum(
        1 for c in test_run.get("cases") or [] if c.get("hidden") and not c.get("passed")
    )

    if not compile_error and not public_failures and not hidden_failed:
        raise JudgeError(
            "Nothing failed in this submission, so there is nothing to nudge about."
        )

    failing = []
    if compile_error:
        failing.append({"id": "compile", "text": "The program did not compile."})
    for f in public_failures:
        failing.append(
            {
                "id": f["id"],
                "text": f"Input {f['input']!r} printed {f['actual']!r}, expected {f['expected']!r}.",
            }
        )
    if hidden_failed:
        failing.append(
            {
                "id": "hidden",
                "text": f"{hidden_failed} case{'s' if hidden_failed > 1 else ''} "
                        "you have not seen also failed.",
            }
        )

    doc = prompts.load_nudge_code()
    model_cfg = doc.get("model", {})
    provider = get_provider(model=model_cfg.get("id"))
    if not provider.has_api_key():
        raise JudgeError(
            f"No API key for provider {provider.name!r}. Set {provider.api_key_env} in the "
            "environment."
        )

    user_prompt = prompts.render_nudge_code_prompt(
        doc, phase, problem, code, public_failures, compile_error,
        hidden_failed, attempt, prior_artifacts,
    )
    result = provider.judge_json(
        system=doc["system_prompt"],
        user=user_prompt,
        model=model_cfg.get("id") or provider.default_model,
        max_output_tokens=int(model_cfg.get("max_output_tokens", 2000)),
        effort=model_cfg.get("effort", "medium"),
        schema=Nudge,
    )
    parsed: Nudge = result.parsed
    known = {f["id"] for f in failing}
    return {
        "summary": parsed.summary,
        # A focus the model invented would point the student at nothing. Fall back to
        # the first real failure rather than rendering a dangling id.
        "focus_id": parsed.focus_id if parsed.focus_id in known else failing[0]["id"],
        "reason": parsed.reason,
        "nudge": parsed.nudge,
        "failing": failing,
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_nudge_code.py -v`
Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add prompts/base/nudge_code.yaml src/clive/prompts.py src/clive/nudge.py tests/test_nudge_code.py
git commit -m "Add the code nudge for tests-gated phases

nudge() refuses to run without failing gating criteria, and a tests-gated phase
has none. This one is handed failing test cases instead, plus the student's own
design -- which is what makes it worth a model call, since the page already
shows the diff. Hidden cases reach the model as a count and never as I/O, which
is asserted against the rendered prompt."
```

---

### Task 9: The student API and its routes

Where the phase becomes live. After this task `/student` still renders a textarea for the code field, but the whole engine behind it works and can be driven with `curl`.

**Files:**
- Modify: `src/clive/studio/student.py`, `src/clive/studio/server.py`
- Test: `tests/test_student_implement.py` (create), `tests/test_student.py` (add one case)

**Interfaces:**
- Consumes: `grade.grade`, `nudge.nudge_code`, `executors.get_executor`, `ExecutorError`.
- Produces:
  - `student.run(body) -> dict` — body `{problem_id, code}`, returns a grade result at `scope="public"`.
  - `student.submit(body)` extended: for a `gate: tests` phase the response adds `"test_run"`, and `"nudge"` is a code nudge.
  - `student.boot()` adds `"executor": {"available", "name", "isolation", "error"}`.
  - `student.problem(slug)` adds `"starter_code"`.
  - Route `POST /api/student/run`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_student_implement.py`:

```python
"""The tests-gated path through the student API.

No compiler and no network: the executor is stubbed, so what is under test is the
branching, the ordering, and the leak guard -- not gcc.
"""

from __future__ import annotations

import pytest

from clive import grade as grading
from clive import nudge as nudging
from clive import prompts
from clive.executors.base import ExecutionResult, RunOutcome
from clive.studio import student

CODE = "#include <stdio.h>\nint main(void){printf(\"3\\n\");return 0;}"


class StubExecutor:
    name, isolation = "stub", "container"

    def __init__(self, stdouts, compiled=True):
        self.stdouts, self.compiled = stdouts, compiled

    def run(self, request):
        if not self.compiled:
            return ExecutionResult(False, "main.c:1: error: boom", "", [])
        return ExecutionResult(
            True, "", "", [RunOutcome("ok", s, "", 0, 1) for s in self.stdouts]
        )


@pytest.fixture
def stub_executor(monkeypatch):
    """Installed into grade, which is where production resolves one."""
    holder = {}

    def install(stdouts, compiled=True):
        holder["e"] = StubExecutor(stdouts, compiled)
        monkeypatch.setattr(grading, "get_executor", lambda: holder["e"])
        return holder["e"]

    return install


@pytest.fixture
def no_judge(monkeypatch):
    """Fails loudly if the judge is called. Several tests assert it is not."""
    def boom(*a, **k):
        raise AssertionError("the judge was called on a submission whose tests failed")

    monkeypatch.setattr(student.judging, "judge", boom)


def submit_body(code=CODE):
    return {"phase_id": "implement", "problem_id": "count_vowels", "code": code,
            "artifact": {"code": code}, "attempt": 1}


def test_run_grades_public_cases_only(stub_executor):
    stub_executor(["3\n", "3\n", "0\n"])
    result = student.run({"problem_id": "count_vowels", "code": CODE})
    assert result["counts"]["total"] == 3
    assert result["passed"]


def test_run_never_returns_a_verdict_or_a_nudge(stub_executor):
    stub_executor(["3\n", "3\n", "0\n"])
    result = student.run({"problem_id": "count_vowels", "code": CODE})
    assert "verdicts" not in result
    assert "nudge" not in result


def test_a_failing_submission_does_not_call_the_judge(stub_executor, no_judge, monkeypatch):
    stub_executor(["9\n", "9\n", "9\n"])
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "0", "reason": "r",
                                         "nudge": "n", "failing": []})
    result = student.submit(submit_body())
    assert not result["passed"]
    assert result["test_run"]["counts"]["failed"] == 3
    assert result["nudge"]["summary"] == "s"
    assert result["verdicts"] == []


def test_a_compile_error_does_not_call_the_judge(stub_executor, no_judge, monkeypatch):
    stub_executor([], compiled=False)
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "compile", "reason": "r",
                                         "nudge": "n", "failing": []})
    result = student.submit(submit_body())
    assert not result["passed"]
    assert not result["test_run"]["compiled"]


def test_passing_every_case_passes_the_phase_and_judges_advisory(stub_executor, monkeypatch):
    stub_executor(["3\n", "3\n", "0\n"])
    criteria = prompts.load_criteria("implement")["criteria"]
    monkeypatch.setattr(student.judging, "judge", lambda *a, **k: {
        "verdicts": [{"criterion_id": c["id"], "verdict": "FAIL", "evidence": "",
                      "confidence": "low", "evidence_found": True} for c in criteria],
        "missing_ids": [],
    })
    result = student.submit(submit_body())
    assert result["passed"], "an advisory FAIL must never hold a tests-gated phase"
    assert result["blocking"] == []
    assert len(result["advisory_unmet"]) == len(criteria)


def test_a_failing_nudge_still_returns_the_test_results(stub_executor, monkeypatch):
    stub_executor(["9\n", "9\n", "9\n"])

    def boom(*a, **k):
        raise nudging.JudgeError("provider down")

    monkeypatch.setattr(student.nudging, "nudge_code", boom)
    result = student.submit(submit_body())
    assert result["nudge_error"] == "provider down"
    assert result["test_run"]["counts"]["failed"] == 3


def test_hidden_cases_are_graded_but_never_described(stub_executor, monkeypatch, tmp_path):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("demo", {
        "statement": "s\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET", "output": "42"}],
    })
    stub_executor(["1\n", "0\n"])
    monkeypatch.setattr(student.nudging, "nudge_code",
                        lambda *a, **k: {"summary": "s", "focus_id": "hidden", "reason": "r",
                                         "nudge": "n", "failing": []})
    body = submit_body()
    body["problem_id"] = "demo"
    result = student.submit(body)
    assert "SECRET" not in str(result)
    assert "42" not in str(result)


def test_problem_carries_starter_code_and_never_hidden_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(prompts, "PROBLEMS_DIR", tmp_path)
    prompts.save_problem("demo", {
        "statement": "s\n",
        "public_test_cases": [{"input": "a", "output": "1"}],
        "hidden_test_cases": [{"input": "SECRET", "output": "42"}],
        "starter_code": "int main(void){}",
    })
    out = student.problem("demo")
    assert out["problem"]["starter_code"] == "int main(void){}"
    assert "hidden_test_cases" not in out["problem"]
    assert "SECRET" not in str(out)


def test_boot_reports_the_executor():
    executor = student.boot()["executor"]
    assert set(executor) == {"available", "name", "isolation", "toolchain", "error"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_student_implement.py -v`
Expected: FAIL — `AttributeError: module 'clive.studio.student' has no attribute 'run'`.

- [ ] **Step 3: Extend the imports and `__all__` in `student.py`**

```python
from clive import grade as grading
from clive import hint as hinting
from clive import judge as judging
from clive import nudge as nudging
from clive import prompts
from clive.executors import ExecutorError, describe_toolchain, get_executor
from clive.providers import get_provider

__all__ = ["boot", "problem", "submit", "run", "hint"]
```

- [ ] **Step 4: Add `describe_toolchain` to the executors package**

The spec asks `boot()` to report the toolchain, so a verdict can be traced to the compiler
that produced it — the local and container backends can disagree. Add to
`src/clive/executors/__init__.py`:

```python
def describe_toolchain(executor: Executor) -> str:
    """What compiled the code, in one line.

    The container backend answers with its image, which is the whole reason it is the
    default: the image is the toolchain. Everything else has to ask the host's gcc, and
    the answer is cached because it cannot change while the process runs.
    """
    if executor.isolation == "container":
        return config.EXECUTOR_IMAGE
    if "gcc" not in _probed:
        try:
            done = subprocess.run(["gcc", "--version"], capture_output=True, text=True, timeout=10)
            _probed["gcc"] = done.stdout.splitlines()[0] if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            _probed["gcc"] = ""
    return _probed["gcc"] or "unknown"
```

with `import subprocess` at the top, `"describe_toolchain"` added to `__all__`, and the
`_probed` annotation widened to `dict[str, bool | str]`.

- [ ] **Step 5: Report the executor in `boot`**

Replace the `return` in `boot()`:

```python
    # The page disables Run honestly rather than failing on click, and a verdict can be
    # traced back to the toolchain that produced it.
    try:
        executor = get_executor()
        executor_info = {
            "available": True,
            "name": executor.name,
            "isolation": executor.isolation,
            "toolchain": describe_toolchain(executor),
            "error": "",
        }
    except ExecutorError as exc:
        executor_info = {
            "available": False, "name": "", "isolation": "", "toolchain": "", "error": str(exc)
        }

    return {
        "phases": phases,
        "problems": prompts.list_problems(),
        "has_api_key": provider.has_api_key(),
        "executor": executor_info,
    }
```

- [ ] **Step 6: Add `starter_code` to `problem`**

In `problem()`, add one key to the returned dict, after `"statement"`:

```python
            "starter_code": doc.get("starter_code", ""),
```

`hidden_test_cases` is not added, and must not be. The dict is built key by key rather than
copied, which is what keeps this safe by construction.

- [ ] **Step 7: Add `run`**

Add after `problem()`:

```python
def run(body: dict) -> dict:
    """Compile and check against the public cases only. No judge, no nudge, no attempt.

    The Run button. It is deliberately not a submission: a student should be able to
    press it as often as they like, and nothing about it is recorded or costs a model
    call. `scope="public"` is fixed here rather than taken from the body, so no request
    can ask this endpoint to run the hidden cases and read back the count.
    """
    prob = prompts.load_problem(body["problem_id"])
    return grading.grade(prob, body.get("code") or "", scope="public")
```

- [ ] **Step 8: Branch `submit` on the gate**

At the top of `submit()`, after `phase, prob, criteria = _context(body)`, insert:

```python
    # Every other gate, named or absent, falls through to the judged path below unchanged.
    if phase.get("gate") == "tests":
        return _submit_tests(phase, prob, criteria, body)
```

Then add the new function below `submit`:

```python
def _submit_tests(phase: dict, prob: dict, criteria: list[dict], body: dict) -> dict:
    """A tests-gated submission: graded first, judged only if it already works.

    The judge is not called on failing code, for two reasons. It spends a call to
    review something the student is about to change anyway; and skipping it means the
    advisory review always reads a working program, so it can be written to comment on
    conformance rather than on correctness.

    `blocking` stays empty because a failing test is not a criterion. Nothing downstream
    should mistake a wrong answer for a rubric failure.
    """
    artifact = body.get("artifact") or {}
    code = body.get("code") or artifact.get("code") or ""
    attempt = int(body.get("attempt", 1))
    prior = body.get("prior_artifacts") or []

    try:
        test_run = grading.grade(prob, code, scope="all")
    except ExecutorError as exc:
        raise judging.JudgeError(str(exc)) from None

    out = {
        "test_run": test_run,
        "verdicts": [],
        "blocking": [],
        "advisory_unmet": [],
        "missing_ids": [],
        "passed": False,
        "nudge": None,
        "nudge_error": None,
    }

    if not test_run["passed"]:
        try:
            out["nudge"] = nudging.nudge_code(phase, prob, code, test_run, attempt, prior)
        except nudging.JudgeError as exc:
            # Losing the nudge must not cost the student the results they waited for.
            out["nudge_error"] = str(exc)
        return out

    out["passed"] = True

    # Advisory review, on code already known to work. A failure here is reported and
    # never bars: `passed` is already true and stays true.
    try:
        result = judging.judge(phase, prob, artifact or {"code": code}, criteria, attempt, prior)
    except judging.JudgeError as exc:
        out["nudge_error"] = str(exc)
        return out

    by_id = {c["id"]: c for c in criteria}
    for v in result["verdicts"]:
        c = by_id.get(v["criterion_id"], {})
        out["verdicts"].append(
            {
                "criterion_id": v["criterion_id"],
                "criterion_text": c.get("text", ""),
                "gate": c.get("gate", prompts.DEFAULT_GATE),
                "verdict": v["verdict"],
                "evidence": v.get("evidence", ""),
                "evidence_found": v.get("evidence_found", True),
            }
        )
    out["advisory_unmet"] = [v["criterion_id"] for v in out["verdicts"] if v["verdict"] == "FAIL"]
    out["missing_ids"] = result["missing_ids"]
    return out
```

- [ ] **Step 9: Add the route**

In `src/clive/studio/server.py`, after the existing `/api/student/submit` route:

```python
    if parts == ["api", "student", "run"] and method == "POST":
        return run_student_code(body)
```

and beside `run_student_submit`:

```python
def run_student_code(body: dict) -> dict:
    """The Run button. An executor failure is the server's problem, not the student's,
    so it comes back as a 502 rather than as a wrong answer."""
    try:
        return studenting.run(body)
    except ExecutorError as exc:
        raise ApiError(str(exc), 502) from None
```

with `from clive.executors import ExecutorError` added to the imports at the top.

- [ ] **Step 10: Add the leak assertion to the existing guard**

Append to `tests/test_student.py`:

```python
def test_no_hidden_test_case_reaches_the_served_page():
    """The same class of rule as the rubric guard: a hidden case is content the
    student must not have, and the served HTML is one view-source away from them."""
    hidden = [
        c
        for meta in prompts.list_problems()
        for c in prompts.load_problem(meta["slug"])["hidden_test_cases"]
    ]
    if not hidden:
        pytest.skip("no hidden cases authored yet")
    html = (STATIC / "student.html").read_text(encoding="utf-8")
    for case in hidden:
        assert case["input"] not in html
        assert str(case["output"]) not in html
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `uv run pytest tests/test_student_implement.py tests/test_student.py -v`
Expected: all pass.

- [ ] **Step 12: Drive it end to end with curl**

```bash
uv run clive-studio --no-browser &
sleep 2
curl -s -X POST localhost:8765/api/student/run \
  -H 'Content-Type: application/json' \
  -d '{"problem_id":"count_vowels","code":"#include <stdio.h>\n#include <string.h>\nint main(void){char l[128];if(!fgets(l,sizeof l,stdin))return 1;int n=0;for(size_t i=0;i<strlen(l);i++){char c=l[i]|32;if(c==97||c==101||c==105||c==111||c==117)n++;}printf(\"%d\\n\",n);return 0;}"}' | head -c 400
kill %1
```
Expected: JSON with `"passed": true` and `"counts": {"passed": 3, ...}`.

- [ ] **Step 13: Commit**

```bash
git add src/clive/studio/ tests/test_student_implement.py tests/test_student.py
git commit -m "Wire the tests-gated path through the student API

submit branches on phase.gate: a tests-gated phase is graded against every case
and judged only when it already passes, so no model call is spent reviewing code
the student is about to change and the advisory review always reads a working
program. blocking stays empty -- a failing test is not a criterion. Adds
/api/student/run for the Run button, which is fixed to the public cases so no
request can ask it to probe the hidden ones."
```

---

### Task 10: The shared Monaco module

**Files:**
- Create: `src/clive/studio/static/editor.js`

**Interfaces:**
- Consumes: nothing.
- Produces: a global `CLiveEditor` with `mount(host, {value, language, readOnly, onChange}) -> {getValue(), setValue(v), layout(), dispose()}`. Falls back to a plain textarea with the same interface when Monaco cannot load, so no caller needs a fallback of its own.

- [ ] **Step 1: Write `editor.js`**

Create `src/clive/studio/static/editor.js`:

```javascript
/* Monaco, mounted the same way by the student page and the Studio's Problem tab.
   One module because two copies of editor setup drift, and the theming is the
   fiddly part: Monaco brings its own colours and would otherwise be the one
   element on the page that ignores the light/dark palette around it.

   Loaded from CDN. The app is already served over a network and already pulls
   fonts from one; vendoring is a change confined to the URL below.

   If Monaco fails to load for any reason, `mount` returns a textarea wearing the
   same interface. A student who cannot reach a CDN must still be able to type. */

(function (global) {
  const CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min";
  let loading = null;

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /* Monaco wants six-digit hex and throws on anything else, so every value is
     validated before it is handed over rather than trusted from the stylesheet. */
  function hex(name, fallback) {
    const v = css(name, fallback);
    return /^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback;
  }

  function defineThemes(monaco) {
    for (const [name, base, surface, ink] of [
      ["clive-light", "vs", hex("--surface", "#ffffff"), hex("--ink", "#14201f")],
      ["clive-dark", "vs-dark", hex("--surface", "#161d1c"), hex("--ink", "#e6ece9")],
    ]) {
      monaco.editor.defineTheme(name, {
        base, inherit: true, rules: [],
        colors: {
          "editor.background": surface,
          "editor.foreground": ink,
          "editorLineNumber.foreground": hex("--ink-3", "#8b9997"),
          "editorGutter.background": surface,
        },
      });
    }
  }

  function isDark() {
    const explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit === "dark";
    return matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function load() {
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = `${CDN}/vs/loader.js`;
      tag.onerror = () => reject(new Error("Monaco could not be loaded."));
      tag.onload = () => {
        global.require.config({ paths: { vs: `${CDN}/vs` } });
        global.require(["vs/editor/editor.main"], () => {
          defineThemes(global.monaco);
          resolve(global.monaco);
        }, reject);
      };
      document.head.append(tag);
    });
    return loading;
  }

  function textareaFallback(host, opts) {
    const ta = document.createElement("textarea");
    ta.value = opts.value || "";
    ta.readOnly = !!opts.readOnly;
    ta.spellcheck = false;
    ta.style.cssText =
      "width:100%;min-height:320px;font-family:var(--mono,monospace);font-size:13px;" +
      "line-height:1.5;padding:10px 12px;border:1px solid var(--line-2,#ccc);" +
      "border-radius:8px;background:var(--paper,#fff);color:var(--ink,#000);resize:vertical";
    ta.addEventListener("input", () => opts.onChange && opts.onChange(ta.value));
    host.replaceChildren(ta);
    return {
      getValue: () => ta.value,
      setValue: (v) => { ta.value = v; },
      layout() {},
      dispose() {},
    };
  }

  /* Returns the handle synchronously so callers never juggle a promise. Monaco
     swaps itself in when it arrives; edits made before then are carried across. */
  function mount(host, opts = {}) {
    const fallback = textareaFallback(host, opts);
    let live = fallback;

    load().then((monaco) => {
      const carried = live.getValue();
      host.replaceChildren();
      host.style.minHeight = "320px";
      const editor = monaco.editor.create(host, {
        value: carried,
        language: opts.language || "c",
        readOnly: !!opts.readOnly,
        theme: isDark() ? "clive-dark" : "clive-light",
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        fontFamily: css("--mono", "monospace"),
        tabSize: 4,
        renderWhitespace: "selection",
      });
      editor.onDidChangeModelContent(() => opts.onChange && opts.onChange(editor.getValue()));
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        monaco.editor.setTheme(isDark() ? "clive-dark" : "clive-light");
      });
      live = {
        getValue: () => editor.getValue(),
        setValue: (v) => { if (editor.getValue() !== v) editor.setValue(v); },
        layout: () => editor.layout(),
        dispose: () => editor.dispose(),
      };
    }).catch(() => { /* the textarea is already mounted and works */ });

    return {
      getValue: () => live.getValue(),
      setValue: (v) => live.setValue(v),
      layout: () => live.layout(),
      dispose: () => live.dispose(),
    };
  }

  global.CLiveEditor = { mount };
})(window);
```

- [ ] **Step 2: Verify it is served**

`_serve_static` already maps `.js` to `text/javascript`, so no server change is needed.

```bash
uv run clive-studio --no-browser &
sleep 2
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' localhost:8765/editor.js
kill %1
```
Expected: `200 text/javascript; charset=utf-8`.

- [ ] **Step 3: Commit**

```bash
git add src/clive/studio/static/editor.js
git commit -m "Add the shared Monaco module

One mount() used by both the student page and the Studio, because two copies of
editor setup drift and the theming is the fiddly part. Falls back to a textarea
wearing the same interface when the CDN cannot be reached, so no caller needs a
fallback of its own and a student without the CDN can still type."
```

---

### Task 11: The Implement phase in the student page

**Files:**
- Modify: `src/clive/studio/static/student.html`

**Interfaces:**
- Consumes: `CLiveEditor.mount`, `POST /api/student/run`, `test_run` on the submit response, `boot().executor`, `problem().starter_code`.
- Produces: no exports — this is the leaf.

- [ ] **Step 1: Load the module and add the styles**

Add before the closing `</head>`, after the existing `<style>` block:

```html
<script src="/editor.js"></script>
```

Append to the stylesheet, beside the existing `.ledger` rules:

```css
  .editor-host { border:1px solid var(--line-2); border-radius:8px; overflow:hidden;
                 min-height:320px; background:var(--paper); }
  .runbar { display:flex; gap:10px; align-items:center; margin-top:14px; flex-wrap:wrap; }
  .runbar .tier { font-family:var(--mono); font-size:11px; color:var(--ink-3);
                  margin-left:auto; }

  .cases-out { margin-top:4px; }
  .cases-out .case { display:flex; gap:12px; padding:11px 0; border-top:1px solid var(--line);
                     align-items:flex-start; }
  .cases-out .case:first-child { border-top:none; }
  .cases-out .io { flex:1; min-width:0; display:grid; gap:7px;
                   grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
  .cases-out .io .k { font-family:var(--mono); font-size:10px; letter-spacing:.09em;
                      text-transform:uppercase; color:var(--ink-3); margin-bottom:2px; }
  .cases-out .io .v { font-family:var(--mono); font-size:12.5px; white-space:pre-wrap;
                      word-break:break-word; background:var(--surface-2); border-radius:5px;
                      padding:5px 8px; }
  .cases-out .io .v.bad { background:var(--block-wash); color:var(--block); }
  .cases-out .hidden-note { font-size:13.5px; color:var(--ink-2); }

  .compile-error { font-family:var(--mono); font-size:12.5px; white-space:pre-wrap;
                   background:var(--block-wash); color:var(--block); border-radius:8px;
                   padding:12px 14px; overflow-x:auto; }
  .warn-block { font-family:var(--mono); font-size:12.5px; white-space:pre-wrap;
                background:var(--advise-wash); color:var(--advise); border-radius:8px;
                padding:10px 12px; overflow-x:auto; margin-bottom:12px; }
```

- [ ] **Step 2: Seed the editor from `starter_code`**

In `freshSession()`, replace the artifact initialiser so a code field starts from the problem's skeleton rather than empty:

```javascript
function freshSession() {
  return S.boot.phases.map((p, i) => ({
    artifact: Object.fromEntries((p.artifact_fields || []).map((f) => [
      f.id,
      f.kind === "code" ? (S.problem && S.problem.starter_code) || "" : "",
    ])),
    attempt: 1, passed: false, unlocked: i === 0,
    result: null, hint: null, history: [], testRun: null,
  }));
}
```

`loadProblem` already sets `S.problem` before calling `freshSession()` in the `fresh` path; confirm the ordering when editing, and if `restore()` returns a session from an older shape, the missing `testRun` key reads as `undefined` and renders nothing.

- [ ] **Step 3: Render the code field with Monaco**

In `renderForm()`, replace the artifact-field loop body with a branch on `kind`:

First add the host cache, beside the other state near the top of the script:

```javascript
/* Editor hosts, cached per phase and field and reused across renders.

   render() rebuilds the whole form on every state change, and a fresh CLiveEditor.mount
   each time would leak one Monaco instance per render and throw away the cursor. Moving
   an existing node into the new tree keeps the instance that is already on it. Cleared
   when the problem changes, because that is a different session. */
const editorHosts = new Map();

function editorHost(f, st) {
  const key = `${S.i}:${f.id}`;
  const cached = editorHosts.get(key);
  if (cached) return cached;
  const host = h("div", { class: "editor-host" });
  editorHosts.set(key, host);
  // Mounted after the node reaches the document, or Monaco measures zero height.
  queueMicrotask(() => CLiveEditor.mount(host, {
    value: st.artifact[f.id] || "",
    language: f.language || "c",
    onChange: (v) => { st.artifact[f.id] = v; save(); },
  }));
  return host;
}
```

and clear it in `loadProblem`, immediately after `S.problem = d.problem;`:

```javascript
  editorHosts.clear();
```

Then the field loop:

```javascript
  for (const f of p.artifact_fields || []) {
    if (f.kind === "code") {
      fields.append(h("div", { class: "fld" }, [
        h("label", { text: f.label || f.id }),
        f.hint ? h("div", { class: "help", text: f.hint }) : null,
        editorHost(f, st),
      ]));
      continue;
    }
    const ta = h("textarea", {
      rows: f.rows || 4, "aria-label": f.label || f.id,
      oninput: (e) => { st.artifact[f.id] = e.target.value; save(); },
    });
    ta.value = st.artifact[f.id] || "";
    fields.append(h("div", { class: "fld" }, [
      h("label", { text: f.label || f.id }),
      f.hint ? h("div", { class: "help", text: f.hint }) : null,
      ta,
    ]));
  }
```

- [ ] **Step 4: Add the Run button to the action bar**

Still in `renderForm()`, immediately before the existing `card.append(acts);`, insert a Run button for a tests-gated phase only:

```javascript
  if (isCodePhase()) {
    const ex = S.boot.executor || {};
    acts.prepend(h("button", {
      class: "btn ghost", type: "button",
      disabled: !!S.busy || empty || !ex.available,
      text: S.busy === "run" ? "Running…" : "Run",
      title: ex.available ? "Check against the examples you were given. Costs nothing."
                          : ex.error || "No compiler is available on the server.",
      onclick: runCode,
    }));
    if (!ex.available) {
      card.append(h("div", { class: "banner err", style: "margin-top:12px",
        text: ex.error || "No compiler is available on the server, so Run and Submit are off." }));
    } else {
      acts.append(h("span", { class: "tier",
        text: `${ex.name} · ${ex.isolation}` }));
    }
  }
```

and add the helper beside `phase()`:

```javascript
/* A phase whose gate is a compiler rather than the judge. The page needs to know
   because Run, the results panel and the editor only belong on that phase. */
const isCodePhase = () => (phase().artifact_fields || []).some((f) => f.kind === "code");
```

Using the field kind rather than a `gate` value is deliberate: `boot()` does not send `gate`, and the page only ever needs to know whether it is rendering an editor.

- [ ] **Step 5: Add the `runCode` action**

Beside `submit()`:

```javascript
async function runCode() {
  const st = cur();
  S.busy = "run"; S.error = null; st.hint = null; render();
  try {
    st.testRun = await api("POST", "/api/student/run", {
      problem_id: S.problem.slug,
      code: st.artifact.code || "",
    });
    // A Run is not a submission: it never clears a verdict list the student is
    // still reading, and it never costs an attempt.
  } catch (e) {
    S.error = e.message;
  } finally {
    S.busy = null; save(); render();
  }
}
```

and extend `submit()` so a tests-gated response keeps its results, by adding one line after `st.result = r;`:

```javascript
    if (r.test_run) st.testRun = r.test_run;
```

Then extend `ctx()` so the code reaches the server under both keys the API accepts:

```javascript
function ctx(extra) {
  return {
    phase_id: phase().phase,
    problem_id: S.problem.slug,
    artifact: cur().artifact,
    code: cur().artifact.code || "",
    attempt: cur().attempt,
    prior_artifacts: priorArtifacts(),
    ...extra,
  };
}
```

- [ ] **Step 6: Render the results panel**

Add beside `renderLedger`:

```javascript
function renderTestRun(tr) {
  const card = h("div", { class: "fb" }, [
    h("h3", { text: tr.compiled
      ? `Test cases — ${tr.counts.passed} of ${tr.counts.total} passing`
      : "It did not compile" }),
  ]);

  if (!tr.compiled) {
    card.append(h("div", { class: "compile-error", text: tr.compile_error.trim() ||
      "The compiler gave no output." }));
    card.append(h("div", { class: "foot",
      text: "Warnings are treated as errors here, so an unused variable will stop the build." }));
    return card;
  }

  if (tr.warnings && tr.warnings.trim()) {
    card.append(h("div", { class: "warn-block", text: tr.warnings.trim() }));
  }

  const list = h("div", { class: "cases-out" });
  tr.cases.forEach((c, i) => {
    const badge = h("span", { class: `badge ${c.passed ? "met" : "block"}`,
      text: c.passed ? "Pass" : "Fail" });
    if (c.hidden) {
      list.append(h("div", { class: "case" }, [badge,
        h("div", { class: "hidden-note",
          text: `A case you have not seen${c.passed ? "" : " — this one did not pass"}.` })]));
      return;
    }
    const cell = (k, v, bad) => h("div", {}, [
      h("div", { class: "k", text: k }),
      h("div", { class: `v ${bad ? "bad" : ""}`, text: v === "" ? "(empty)" : v }),
    ]);
    const io = h("div", { class: "io" }, [
      cell("Input", c.input),
      cell("Expected", c.expected),
      cell(c.status === "ok" ? "Your output" : c.status.replace("_", " "),
           c.status === "timeout" ? "(it ran too long and was stopped)" : c.actual,
           !c.passed),
    ]);
    list.append(h("div", { class: "case" }, [badge, io]));
  });
  card.append(list);
  return card;
}
```

- [ ] **Step 7: Place it in the stage**

In `renderStage()`, insert the results panel immediately before the nudge, so a student reads what failed before reading what to do about it:

```javascript
  if (st.testRun) out.push(renderTestRun(st.testRun));
  if (r && r.nudge) out.push(renderNudge(r.nudge));
```

Then adjust the busy indicator's text so Run does not claim to be judging:

```javascript
      h("span", { text: S.busy === "submit"
        ? "Checking your work against every requirement…"
        : S.busy === "run"
        ? "Compiling and running your program…"
        : "Looking for somewhere useful to point…" }),
```

And update the closing message so it no longer says implementation comes next:

```javascript
    out.push(h("div", { class: "card done" }, [
      h("h2", { text: "Every phase passed" }),
      h("p", { text: "A definition you wrote yourself, cases you worked by hand, a plan that accounts for them, and a program that carries it out." }),
    ]));
```

- [ ] **Step 8: Verify by hand**

```bash
uv run clive-studio
```
Open `http://127.0.0.1:8765/student`, pick **Count Vowels**, and check each of:
1. Phases 1-3 render textareas exactly as before — no editor, no Run button, no regression.
2. Skipping to Implement is not possible until Design passes (use the Studio Sandbox if you want to reach it quickly without spending judge calls).
3. The Implement phase shows Monaco, seeded with the starter code, with C syntax highlighting.
4. **Run** with the starter code returns failing cases with input, expected and actual.
5. A deliberate syntax error shows gcc's stderr in the compile-error block.
6. An unused variable is reported as a compile error, and the footnote explains why.
7. Reloading the page keeps the code — it is in `localStorage` with the rest of the artifact.
8. Toggling the OS to dark mode repaints the editor to match the page.

- [ ] **Step 9: Verify no hidden case leaked into the page**

Run: `uv run pytest tests/test_student.py -v`
Expected: green, including the new `test_no_hidden_test_case_reaches_the_served_page`.

- [ ] **Step 10: Commit**

```bash
git add src/clive/studio/static/student.html
git commit -m "Add the Implement phase to the student page

Monaco for the one field marked kind: code, seeded from the problem's starter
code and persisted with the rest of the artifact. Run checks the examples the
student was given and costs nothing; Submit runs everything and then judges. A
compile error replaces the case list with gcc's stderr, and warnings render as
their own state rather than as a wrong answer."
```

---

### Task 12: Authoring starter code and hidden cases in the Studio

**Files:**
- Modify: `src/clive/studio/static/index.html`

**Interfaces:**
- Consumes: `CLiveEditor.mount`, `starter_code` and `hidden_test_cases` on the problem document.
- Produces: no exports.

- [ ] **Step 1: Load the module**

Add `<script src="/editor.js"></script>` to the `<head>` of `index.html`, matching Task 11.

- [ ] **Step 2: Extract the test-case table into a helper**

In `renderProblem()`, the public-case block is about to be needed twice. Replace it with a function defined just above `renderProblem`:

```javascript
/* One test-case table. Used for both lists: they differ only in which key they
   write and in what the student is allowed to see, never in how they are edited. */
function testCaseTable(list, onChange) {
  const cases = el("div");
  if (!list.length) cases.append(el("p", { className: "empty", textContent: "None yet." }));

  list.forEach((tc, i) => {
    const head = el("div", { className: "head" }, [el("div", { className: "grip", textContent: `#${i + 1}` })]);
    head.append(...reorderControls(list, i, onChange));
    const del = el("button", { className: "mini", textContent: "Remove" });
    del.onclick = () => { list.splice(i, 1); onChange(); };
    head.append(el("div", { style: "flex:1" }), del);

    cases.append(el("div", { className: "item" }, [
      head,
      el("div", { className: "row" }, [
        field("input", textArea(tc.input, (v) => { tc.input = v; markDirty("problem"); }, 3, true)),
        field("output", textArea(tc.output, (v) => { tc.output = v; markDirty("problem"); }, 3, true)),
      ]),
    ]));
  });

  const add = el("button", { className: "act ghost", textContent: "+ Add test case" });
  add.onclick = () => { list.push({ input: "", output: "" }); onChange(); };
  return [cases, add];
}
```

Then in `renderProblem`, replace the inline block with:

```javascript
  const onCases = () => { markDirty("problem"); render(); };
  const publicList = p.public_test_cases || (p.public_test_cases = []);
  const hiddenList = p.hidden_test_cases || (p.hidden_test_cases = []);

  out.append(el("div", { className: "card" }, [
    el("h3", { textContent: "Public test cases" }),
    el("p", {
      className: "sub",
      textContent: "Given to the student, shown on the problem brief, and checked by Run. "
        + "Also shown to the judge as context, which is told never to quote them as evidence.",
    }),
    ...testCaseTable(publicList, onCases),
  ]));

  out.append(el("div", { className: "card" }, [
    el("h3", { textContent: "Hidden test cases" }),
    el("p", {
      className: "sub",
      textContent: "Checked only on Submit, and never sent to the browser — the student is "
        + "told a hidden case failed and nothing else. Nothing here reaches a nudge prompt "
        + "either, so do not rely on one to explain a failure the student cannot see.",
    }),
    ...testCaseTable(hiddenList, onCases),
  ]));
```

- [ ] **Step 3: Add the starter-code editor**

After the hidden-cases card in `renderProblem`:

```javascript
  const starterHost = el("div", { className: "editor-host", style: "min-height:260px" });
  queueMicrotask(() => {
    if (!starterHost.isConnected) return;
    CLiveEditor.mount(starterHost, {
      value: p.starter_code || "",
      language: "c",
      onChange: (v) => { p.starter_code = v; markDirty("problem"); },
    });
  });

  out.append(el("div", { className: "card" }, [
    el("h3", { textContent: "Starter code" }),
    el("p", {
      className: "sub",
      textContent: "What the student's editor opens with. It must compile: with -Werror in "
        + "play, a skeleton that does not build makes a student's first Run fail before they "
        + "have written anything. Give it a main() that reads the input and prints nothing "
        + "useful, and let them fill in the middle.",
    }),
    starterHost,
  ]));
```

Add the `.editor-host` rule to `index.html`'s stylesheet (the student page's copy is not shared):

```css
.editor-host { border:1px solid var(--line); border-radius:8px; overflow:hidden;
               min-height:260px; background:var(--bg); }
```

- [ ] **Step 4: Seed the two keys in `newProblem`**

In the `api("PUT", ...)` body inside `newProblem`, add:

```javascript
      hidden_test_cases: [],
      starter_code: "#include <stdio.h>\n\nint main(void) {\n    return 0;\n}\n",
```

- [ ] **Step 5: Verify by hand**

```bash
uv run clive-studio
```
1. Problem tab shows three cards: public cases, hidden cases, starter code.
2. Add a hidden case, save, and confirm `git diff cases/problems/<slug>.yaml` shows only `hidden_test_cases` added.
3. Open a problem with neither key and save it unchanged — `git diff` must be empty. This is what Task 2's "omit when empty" rule buys, and it is the one regression that would dirty all nine files.
4. Edit the starter code, save, reload, and confirm it round-trips.

- [ ] **Step 6: Commit**

```bash
git add src/clive/studio/static/index.html
git commit -m "Author starter code and hidden test cases in the Studio

The public and hidden lists share one table helper -- they differ in what the
student may see, never in how they are edited. Starter code gets the same Monaco
module as the student page, with a note that it has to compile: under -Werror a
skeleton that does not build fails a student's first Run before they have
written anything."
```

---

### Task 13: The Implement phase in the Sandbox Session

**Files:**
- Modify: `src/clive/studio/static/index.html`

**Interfaces:**
- Consumes: `CLiveEditor.mount`, `POST /api/student/run`, `POST /api/judge`, `grade` via the student routes.
- Produces: no exports.

- [ ] **Step 1: Render the code field in the session form**

In the Session tab's artifact-field loop, branch on `kind` exactly as the student page does:

The Studio re-renders on every state change exactly as the student page does, so the
host is cached for the same reason. Add beside the Session tab's other helpers:

```javascript
/* One Monaco per phase and field, reused across renders. See the student page's
   editorHost for why. Cleared when the session restarts or the problem changes. */
const sessionEditorHosts = new Map();

function sessionEditorHost(f, st) {
  const key = `${S.phaseId}:${f.id}`;
  const cached = sessionEditorHosts.get(key);
  if (cached) return cached;
  const host = el("div", { className: "editor-host" });
  sessionEditorHosts.set(key, host);
  queueMicrotask(() => CLiveEditor.mount(host, {
    value: st.artifact[f.id] || "",
    language: f.language || "c",
    onChange: (v) => { st.artifact[f.id] = v; writeSandbox(); },
  }));
  return host;
}
```

Call `sessionEditorHosts.clear()` in `freshSession` and in the Session's problem picker.
Then the field loop:

```javascript
  for (const f of fields) {
    if (f.kind === "code") {
      form.append(field(f.label || f.id, sessionEditorHost(f, st), f.hint));
      continue;
    }
    form.append(field(
      f.label || f.id,
      textArea(st.artifact[f.id] || "", (v) => { st.artifact[f.id] = v; writeSandbox(); }, f.rows || 4),
      f.hint,
    ));
  }
```

- [ ] **Step 2: Seed the sandbox session from starter code**

In `freshSession(problemSlug)`, initialise a code field from the loaded problem's starter code, matching the student page:

```javascript
      artifact: Object.fromEntries((p.artifact_fields || []).map((f) => [
        f.id,
        f.kind === "code" ? (S.problem && S.problem.starter_code) || "" : "",
      ])),
```

- [ ] **Step 3: Add Run and route Submit through the tests path**

The Session tab judges through `/api/judge` against the sandbox copy, but grading needs the problem's cases and an executor, which `/api/student/run` already provides and which does not read the sandbox. That is the correct trade: the sandbox exists to experiment with *rubrics and prompts*, and a scratch copy of a test case is not a rubric experiment. Add a Run button that grades the **saved** problem, and label it so the distinction is visible:

Append it to the `form` card built in Step 1, which is the one container the Session's
phase form definitely owns — the Submit and hint buttons are assembled further down and
their container is not named consistently:

```javascript
  if ((S.phase.artifact_fields || []).some((f) => f.kind === "code")) {
    const runBtn = el("button", { className: "act ghost", textContent: "Run" });
    runBtn.title = "Compiles and checks the public cases of the SAVED problem — "
      + "test cases are not part of the sandbox.";
    runBtn.onclick = async () => {
      try {
        st.testRun = await api("POST", "/api/student/run", {
          problem_id: S.problemSlug, code: st.artifact.code || "",
        });
        writeSandbox();
        render();
      } catch (e) { say(e.message, "err"); }
    };
    form.append(el("div", { className: "row", style: "margin-top:12px" }, [runBtn]));
  }
```

- [ ] **Step 4: Render the results**

Reuse the shape from Task 11 by adding a compact renderer to `index.html` beside `renderNudge`:

```javascript
function renderSessionTestRun(tr) {
  const card = el("div", { className: "card" }, [
    el("h3", { textContent: tr.compiled
      ? `Test cases — ${tr.counts.passed} of ${tr.counts.total} passing`
      : "It did not compile" }),
  ]);
  if (!tr.compiled) {
    card.append(el("pre", { className: "mono", textContent: tr.compile_error.trim() }));
    return card;
  }
  if (tr.warnings && tr.warnings.trim()) {
    card.append(el("div", { className: "note warn", textContent: tr.warnings.trim() }));
  }
  for (const c of tr.cases) {
    card.append(el("div", { className: "item" }, [
      el("div", { className: "head" }, [
        el("span", { className: c.passed ? "pill ok" : "pill bad",
                     textContent: c.passed ? "PASS" : "FAIL" }),
        el("span", { textContent: c.hidden ? "hidden case"
          : `input ${JSON.stringify(c.input)} → ${JSON.stringify(c.actual)} `
            + `(expected ${JSON.stringify(c.expected)})` }),
      ]),
    ]));
  }
  return card;
}
```

and render it in the Session stage before the nudge:

```javascript
  if (st.testRun) out.append(renderSessionTestRun(st.testRun));
```

- [ ] **Step 5: Verify by hand**

```bash
uv run clive-studio
```
1. **Enter sandbox**, open **Session**, use **Skip ahead** from Design to unlock Implement.
2. The editor appears with the starter code; Run compiles and reports cases.
3. Its tooltip says test cases come from the saved problem, not the sandbox.
4. `git status` stays clean throughout — the sandbox writes nothing.

- [ ] **Step 6: Commit**

```bash
git add src/clive/studio/static/index.html
git commit -m "Add the Implement phase to the Sandbox Session

Run grades the saved problem's cases rather than a sandbox copy, and says so in
its tooltip: the sandbox exists to experiment with rubrics and prompts, and a
scratch copy of a test case is not a rubric experiment."
```

---

### Task 14: Documentation

**Files:**
- Modify: `README.md`, `prompts/CHANGELOG.md`, `.env.example`

- [ ] **Step 1: Record the prompt changes**

Prepend to `prompts/CHANGELOG.md` — the repo's convention is to record *why*, not just what:

```markdown
## 2026-09-07 — implement.yaml v1, nudge_code.yaml v1

Adds the fourth PCDIT phase, and with it the first prompt in this repo that is not
judging prose.

`phases/implement.yaml` v1. Its system prompt inverts one rule the other three share:
there, EARLIER PHASES is context that must never be quoted; here the earlier phases are
the *standard being applied*, because every criterion asks whether the program matches
the plan. Evidence is still a span of the student's code. The prompt also states that
correctness is settled before it runs — the judge is only called once every test passes —
so it can be written to comment on conformance without hedging about bugs.

`base/nudge_code.yaml` v1. A separate document from `base/nudge.yaml` because the two take
different inputs: that one is handed failing gating criteria, this one failing test cases
and a compiler. It exists to say something the diff cannot — where the program stopped
following the plan. Hidden cases reach it as a count and never as I/O.
```

- [ ] **Step 2: Document the environment variables**

Append to `.env.example`:

```
# Which sandbox compiles and runs student C. Unset probes and takes the strongest
# that works: container (podman/docker), then local-bwrap, then local.
# CLIVE_EXECUTOR=container

# The image the container backend uses. It pins gcc, which is what makes two
# participants on two machines get the same verdict for the same code.
# CLIVE_EXECUTOR_IMAGE=docker.io/library/gcc:14

# The weakest isolation this host will accept: container, namespace, or rlimit.
# Serving several participants from one box, set this to namespace or better.
# CLIVE_SANDBOX_FLOOR=rlimit

# Compiles running at once.
# CLIVE_MAX_CONCURRENT_RUNS=4
```

- [ ] **Step 3: Update the README**

Three edits:

1. **"The three phases" becomes "The four phases."** Replace the section's opening line — currently *"The first three steps of PCDIT, the ones where a judge reads prose rather than code. Implement and Test stay with AnimoRank's autograder."* — with:

```markdown
The first four steps of PCDIT. The first three are judged by a model reading prose; the
fourth is gated by a compiler, and the model only reviews code that already works. Test
stays with AnimoRank's autograder.
```

and add the row to the table:

```markdown
| **Implement** | `implement` | A C program, checked against the problem's test cases |
```

2. **Add a section after "The student view"**, documenting the phase honestly:

```markdown
## The Implement phase

The fourth phase is the first whose gate is not a judge. The student writes C in an
editor, **Run** checks it against the examples they were given, and **Submit** checks it
against those plus cases they have not seen. Every case must pass; the model gets no vote
on that.

Once it passes, the code is judged once more against the student's own Problem, Cases and
Design — not for bugs, which the tests have already settled, but for whether the program
is the plan. Every criterion in `criteria/implement.yaml` is advisory and
`tests/test_implement_content.py` fails the suite if one is not: a gating criterion there
would let the judge bar code that demonstrably works.

**A failing submission is not judged at all.** It is nudged instead, by
`prompts/base/nudge_code.yaml`, which sees the code, the failing public cases, and the
student's design — so it can say where the program stopped following the plan rather than
restating the diff the page already shows.

**Where the code runs.** `src/clive/executors/` mirrors `src/clive/providers/`: one file
per backend, a registry, and an environment variable to pick. `get_executor()` probes and
takes the strongest that works — a container (podman or docker, with the image pinning
gcc), then bubblewrap, then bare rlimits — and `CLIVE_SANDBOX_FLOOR` refuses anything
weaker than you specify. Set it to `namespace` or better on a host serving more than one
person. `bwrap`'s probe runs bubblewrap rather than testing for the binary, because it can
be installed and still fail where unprivileged user namespaces are restricted.

**Contract, and where it differs from AnimoRank.** The compile and run lines are
AnimoRank's verbatim (`gcc -Werror -Wall -o program *.c -lm -lpthread`, then `./program`),
and so is the public/all split between Run and Submit. Four things differ, and the first
is load-bearing:

- **Trailing whitespace is normalised before comparison.** AnimoRank compares stdout
  strictly. Every problem in `cases/problems/` stores its expected output without a
  trailing newline, so a strict comparison rejects a correct program that ends with
  `printf("%d\n", ...)` — on all nine.
- Compiled once and run N times, rather than once per case.
- 5s per run rather than 30, with the memory cap applied to the run and never to gcc.
- `FunctionOutputTestCase` is not ported. `crowley_path` gets its `solvePath()` harness
  through `starter_code` instead.
```

3. **Add to the Layout block**:

```
src/clive/executors/         one file per sandbox backend; CLIVE_EXECUTOR picks which
src/clive/grade.py           one submission against a problem's test cases
src/clive/studio/static/editor.js   the Monaco module, shared by both pages
```

- [ ] **Step 4: Verify the README's claims are true**

Every factual claim above is asserted by a test. Confirm the suite is green, then confirm the two claims a test cannot make:

```bash
uv run pytest
grep -c "hidden_test_cases" README.md
```
Expected: green suite; the README mentions the feature.

- [ ] **Step 5: Commit**

```bash
git add README.md prompts/CHANGELOG.md .env.example
git commit -m "Document the Implement phase

Records the four divergences from AnimoRank in the README, the trailing-newline
rule first, since it is the one that would otherwise look like a bug rather than
a decision."
```

---

## Verification

Run after the final task:

```bash
uv run pytest -v
uv run python -c "from clive.executors import available_executors; print([c.name for c in available_executors()])"
git status --short
```

Expected: the whole suite green; at least one executor available; a clean tree.

Then one full pass by hand through `/student` on **Count Vowels**: write the definition, the cases, the design, then the program — and confirm the fourth phase gates on the compiler, nudges when a case fails, and reviews the code against the design once every case passes.
