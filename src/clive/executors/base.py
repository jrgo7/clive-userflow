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
    #: Best-effort cap on the work directory's total size, checked once after each run
    #: -- see LocalExecutor.execute. local/local-bwrap already bound this harder, with
    #: RLIMIT_FSIZE applied straight to the student's process; this exists for the
    #: container backend, which has no such rlimit (a Python rlimit would cap the
    #: podman/docker client, not the containerized program -- see
    #: ContainerExecutor.preexec_for_run) and would otherwise report `ok` for a run
    #: that filled its work directory's bind mount. A post-hoc check, not a hard cap:
    #: it cannot stop the bytes from landing on host disk within the run's own time
    #: budget, only stop the run from being misreported as successful once they have.
    workdir_bytes: int = 256 * 1024 * 1024


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


RunStatus = Literal["ok", "timeout", "runtime_error", "output_truncated", "disk_exceeded"]


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
