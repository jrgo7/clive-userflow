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

    `nproc_ceiling` is `limits.pids` plus an ambient-task count taken in the parent
    once for the request, so `limits.pids` means "budget above whatever the host is
    already doing" rather than an absolute cap -- see `_ambient_task_count`.
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
    buffered while draining it. Instead this reads both streams through a single
    `select.select` loop and kills the process group the instant either stream's
    accumulated size passes `output_bytes`.

    Writing stdin happens inside that same loop rather than as a separate blocking
    step beforehand: a child that never reads stdin (it does not call `scanf`, say)
    while flooding its own stdout would otherwise deadlock a blocking write against
    the child's own full, undrained pipe -- and since that write sits before the read
    loop even starts, `run_seconds` (enforced only inside the loop) would never fire
    either. Stdin's fd is made non-blocking and folded into `select`'s writable set
    alongside the two readable ones, so nothing here can block outside the one loop
    that already knows how to enforce the deadline and the byte cap.
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
        stdout_fd, stderr_fd = proc.stdout.fileno(), proc.stderr.fileno()
        chunks: dict[int, list[bytes]] = {stdout_fd: [], stderr_fd: []}
        sizes = {stdout_fd: 0, stderr_fd: 0}
        readable = {stdout_fd, stderr_fd}
        timed_out = False
        output_capped = False
        deadline = time.monotonic() + timeout

        # None until there is unwritten stdin; cleared (and the pipe closed) once
        # everything has been written, or the child turns out never to read it.
        stdin_fd = None
        pending_stdin = b"" if stdin_text is None else stdin_text.encode("utf-8", errors="replace")
        if pending_stdin:
            stdin_fd = proc.stdin.fileno()
            os.set_blocking(stdin_fd, False)
        else:
            try:
                proc.stdin.close()
            except OSError:
                pass

        while readable or stdin_fd is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            writable = [stdin_fd] if stdin_fd is not None else []
            ready_r, ready_w, _ = select.select(list(readable), writable, [], remaining)
            if not ready_r and not ready_w:
                continue  # select's own timeout elapsed; the top of the loop marks it

            if stdin_fd is not None and stdin_fd in ready_w:
                try:
                    written = os.write(stdin_fd, pending_stdin[:65536])
                    pending_stdin = pending_stdin[written:]
                except (BrokenPipeError, OSError):
                    # The child exited, or will never read the rest -- give up on it
                    # rather than spin re-offering a fd that keeps coming back ready.
                    pending_stdin = b""
                if not pending_stdin:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    stdin_fd = None

            for fd in ready_r:
                chunk = os.read(fd, 65536)
                if not chunk:
                    readable.discard(fd)
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
        for stream in (proc.stdin, proc.stdout, proc.stderr):
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

            # Measured once per request, immediately before the first run, rather than
            # once per stdin: ambient load does shift over time, but not meaningfully
            # within the few seconds one request's runs take, and re-walking all of
            # /proc before every single stdin is wasted work for a request with many
            # test cases.
            nproc_ceiling = _ambient_task_count() + limits.pids

            runs = []
            for stdin_text in request.stdins:
                started = time.monotonic()
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

        The probe binds the same `_SYSTEM_PATHS` set `wrap()` uses, rather than a
        smaller hand-picked set, so it exercises the actual sandbox shape and isn't
        fragile to a distribution's particular symlink layout. A minimal `--ro-bind
        /usr /usr` plus a `/bin -> usr/bin` symlink looks sufficient on a typical
        merged-/usr host, but fails on one where `/lib64` is its own top-level
        symlink (e.g. Arch Linux's `/lib64 -> usr/lib`): the dynamic loader at
        `/lib64/ld-linux-x86-64.so.2` is then unreachable inside that minimal root,
        and even `/bin/true` fails to exec -- not because bwrap itself doesn't work,
        but because the probe's own sandbox was incomplete.
        """
        if not super().probe() or shutil.which("bwrap") is None:
            return False
        cmd = ["bwrap", "--unshare-all", "--die-with-parent"]
        for path in _SYSTEM_PATHS:
            if os.path.exists(path):
                cmd += ["--ro-bind", path, path]
        cmd += ["--proc", "/proc", "--dev", "/dev", "--", "/bin/true"]
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=10)
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
