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
