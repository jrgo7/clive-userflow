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
import select
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


def _ambient_task_count() -> int:
    """Best-effort count of tasks already charged against our real UID's RLIMIT_NPROC.

    RLIMIT_NPROC is enforced by the kernel against the real UID's total task count
    *system-wide* -- and Linux counts each thread as its own task, not just each
    top-level process. On an ordinary interactive desktop this is easily four
    figures: measured ~1470 threads for one user on the machine this was written on
    (mostly threads inside a browser and an editor), against ~120 top-level processes
    for that same user -- and none of it has anything to do with the student's
    program. Treating `limits.pids` as an absolute ceiling on RLIMIT_NPROC therefore
    rejects a correct program's very first fork() purely because of ambient load.

    Counting only top-level `/proc/<pid>` entries is the obvious simpler proxy, but
    it was measured insufficient on this machine: it undercounts by roughly 12x here,
    since it counts each process once no matter how many threads it has. So this
    sums `/proc/<pid>/task` (every thread, not just each thread-group leader) across
    processes owned by our UID. The scan inevitably races a moving target; any read
    that fails because a task exited mid-scan is just skipped rather than raised --
    this is inherently best-effort.
    """
    uid = os.getuid()
    total = 0
    try:
        entries = os.listdir("/proc")
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            owner = None
            with open(f"/proc/{entry}/status") as f:
                for line in f:
                    if line.startswith("Uid:"):
                        owner = int(line.split()[1])
                        break
            if owner != uid:
                continue
            total += len(os.listdir(f"/proc/{entry}/task"))
        except (OSError, ValueError, IndexError):
            continue
    return total


def _rlimits(limits: Limits, nproc_ceiling: int):
    """Applied in the child, between fork and exec. Run step only.

    `nproc_ceiling` is `limits.pids` plus a fresh ambient-task count taken in the
    parent right before this runs, so `limits.pids` means "budget above whatever the
    host is already doing" rather than an absolute cap -- see `_ambient_task_count`.
    """

    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_mb << 20,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (limits.run_seconds + 1,) * 2)
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc_ceiling,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.output_bytes * 16,) * 2)

    return apply


def _spawn(argv, cwd, stdin_text, timeout, preexec) -> tuple[int, str, str, bool]:
    """Run one command to completion. Returns (exit_code, stdout, stderr, timed_out).

    `start_new_session` puts the child in its own process group so a timeout kills its
    children too; without it a forking program outlives the request. Compile step
    only -- compiler output is small and already time-bounded, so draining it with a
    blocking `communicate()` is fine. `_spawn_capped` below is the run-step
    equivalent, which also bounds memory rather than just wall clock.
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


def _spawn_capped(
    argv, cwd, stdin_text, timeout, preexec, output_bytes,
) -> tuple[int, str, str, bool, bool]:
    """Run one command to completion, capping memory as well as wall clock.

    Returns (exit_code, stdout, stderr, timed_out, output_capped). Unlike `_spawn`,
    this never calls `communicate()`: that drains a child's pipes to completion (EOF
    or timeout) fully into memory before anyone gets a chance to truncate, so a
    flooding program was bounded in wall time but not in the bytes this process
    buffered while draining it. Instead this reads both streams through a
    `select.select` loop and kills the process group the instant either stream's
    accumulated size passes `output_bytes`. Selecting on both fds together, rather
    than reading one to completion before the other, is what avoids the classic
    two-pipe deadlock -- a child that fills stdout while this process is blocked
    reading only stderr, or vice versa.
    """
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, preexec_fn=preexec,
        )
    except OSError as exc:
        raise ExecutorError(f"Could not start {argv[0]!r}: {exc}") from None

    try:
        # Stdins in this codebase are short and a program reads them eagerly (or not
        # at all), so this write never contends with the read loop below.
        if stdin_text is not None:
            try:
                proc.stdin.write(stdin_text.encode("utf-8", errors="replace"))
            except (BrokenPipeError, OSError):
                pass
        try:
            proc.stdin.close()
        except OSError:
            pass

        stdout_fd, stderr_fd = proc.stdout.fileno(), proc.stderr.fileno()
        chunks: dict[int, list[bytes]] = {stdout_fd: [], stderr_fd: []}
        sizes = {stdout_fd: 0, stderr_fd: 0}
        open_fds = {stdout_fd, stderr_fd}
        timed_out = False
        output_capped = False
        deadline = time.monotonic() + timeout

        while open_fds:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select(list(open_fds), [], [], remaining)
            if not ready:
                continue  # select's own timeout elapsed; the top of the loop marks it
            for fd in ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    open_fds.discard(fd)
                    continue
                chunks[fd].append(chunk)
                sizes[fd] += len(chunk)
            if sizes[stdout_fd] > output_bytes or sizes[stderr_fd] > output_bytes:
                output_capped = True
                break

        if timed_out or output_capped:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        exit_code = proc.returncode if proc.returncode is not None else -1
        stdout = b"".join(chunks[stdout_fd]).decode("utf-8", errors="replace")
        stderr = b"".join(chunks[stderr_fd]).decode("utf-8", errors="replace")
        return exit_code, stdout, stderr, timed_out, output_capped
    finally:
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


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
                # Measured fresh for each run, immediately before Popen: ambient load
                # is a moving target, and stale numbers from earlier in this request
                # would drift as other processes on the host come and go.
                nproc_ceiling = _ambient_task_count() + limits.pids
                rc, out, err, ran_out, output_capped = _spawn_capped(
                    self.wrap(request.run_argv, workdir), workdir,
                    stdin_text, limits.run_seconds,
                    _rlimits(limits, nproc_ceiling), limits.output_bytes,
                )
                duration = int((time.monotonic() - started) * 1000)

                out = out[: limits.output_bytes]
                err = err[: limits.output_bytes]

                if ran_out:
                    status = "timeout"
                elif output_capped:
                    status = "output_truncated"
                elif rc != 0:
                    status = "runtime_error"
                else:
                    status = "ok"
                runs.append(RunOutcome(status, out, err, rc, duration))

            return ExecutionResult(True, "", cerr, runs)
