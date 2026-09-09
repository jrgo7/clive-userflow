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
import tempfile
from pathlib import Path

from clive import config
from clive.executors.base import ExecutorError, Limits
from clive.executors.local import LocalExecutor


class ContainerExecutor(LocalExecutor):
    name = "container"
    isolation = "container"

    #: Resolved by probe(). podman is preferred: it needs no daemon, so a rootless
    #: install works where docker would need a running service.
    runtime: str | None = None

    @staticmethod
    def preexec_for_run(limits: Limits, nproc_ceiling: int):
        """None: the limits below are the container's, and applying them to the client
        process instead would cap podman rather than the student's program."""
        return None

    @classmethod
    def wrap_with(
        cls, argv: list[str], workdir: Path, limits: Limits, is_compile: bool,
    ) -> list[str]:
        if cls.runtime is None:
            raise ExecutorError(
                "ContainerExecutor has no probed runtime. Call probe() first (or go "
                "through get_executor(), which always does) rather than constructing "
                "this class directly."
            )
        cmd = [
            cls.runtime, "run", "--rm",
            # Without this, podman leaves the container's stdin closed (EOF)
            # regardless of what the client writes to the pipe -- a program that
            # calls scanf() would see immediate EOF rather than the intended input.
            "--interactive",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "--cpus", "1",
            # Read-write: gcc writes `program` here and the run step executes it.
            # --read-only still covers the container's own root filesystem.
            "--volume", f"{workdir}:/work:rw",
            "--workdir", "/work",
        ]
        if is_compile:
            # Never --memory or --pids-limit here: base.py's Limits.compile_seconds
            # docstring states the rule this backend must keep too -- gcc "is never
            # given memory_mb: the compiler routinely needs more than a student's
            # program is allowed, and an RLIMIT_AS that killed gcc would surface as a
            # compile error on correct code". LocalExecutor/BwrapExecutor keep this by
            # passing preexec=None to the compile spawn; the container-flag
            # equivalent is simply not passing --memory/--pids-limit at all.
            timeout_seconds = limits.compile_seconds + 5
        else:
            cmd += ["--memory", f"{limits.memory_mb}m", "--pids-limit", str(limits.pids)]
            timeout_seconds = limits.run_seconds + 5
        cmd.append(config.EXECUTOR_IMAGE)
        # A CLI --timeout flag would be the obvious way to bound this, and podman has
        # one -- but docker's `run` does not ("unknown flag: --timeout", exit 125),
        # verified empirically. Passing it unconditionally made every compile fail on
        # a docker-only host, on the strongest isolation tier, reported to the student
        # as a compile error on correct code. Wrapping the in-container command with
        # coreutils' own `timeout` instead needs no runtime-specific flag at all: gcc:14
        # ships coreutils, so this is identical on both runtimes and self-enforcing --
        # it runs and kills inside the container's own PID namespace, so the container
        # still stops itself even if the client process (this Python process, or the
        # podman/docker CLI it launched) is killed before the run's own timeout fires.
        # `-k 1` sends TERM, then KILL a second later if TERM did not finish the job.
        return cmd + ["timeout", "-k", "1", str(timeout_seconds)] + argv

    def execute(self, request):
        # `wrap` has no limits argument, so bind them for this call. The base class
        # calls self.wrap(argv, workdir) for both the compile and the run, passing
        # the literal request.compile_argv/request.run_argv objects through
        # unchanged (local.py:275, local.py:294) -- so comparing by identity against
        # the captured compile_argv reliably tells wrap_with which step it is
        # building a command for.
        limits = request.limits
        compile_argv = request.compile_argv
        # Safe only because get_executor() constructs a fresh instance per call --
        # this mutates instance state, so reusing one instance across requests would
        # let one request's limits leak into another's container invocation.
        self.wrap = lambda argv, workdir: self.wrap_with(
            argv, workdir, limits, is_compile=(argv is compile_argv)
        )
        return super().execute(request)

    @classmethod
    def probe(cls) -> bool:
        """Run a real container through `wrap_with` itself, not a hand-rebuilt argv.

        Same principle as `BwrapExecutor.probe`'s own docstring, and guarding against
        exactly the class of bug it names: installed but broken. Checking `image
        exists`/`image inspect` alone only proves podman or docker can see the image --
        that passed cleanly on a docker-only host running gcc:14 while every real
        compile then failed with exit 125, because `wrap_with` was passing podman's
        `--timeout` flag to docker too. Running `wrap_with`'s own output -- the literal
        command a real compile or run will use, not a second list that merely claims to
        agree with it -- is what would have caught that, and is what makes the same
        class of bug structurally hard to reintroduce: any future flag `wrap_with`
        grows either works on both runtimes or fails right here, before a single
        student's compile does.

        `cls.runtime` is set before calling `wrap_with` (which requires it) and
        unset again if this runtime does not actually work, so a probe that tries
        podman then docker never leaves a failed runtime's name behind for the next
        one to trip over.
        """
        for runtime in ("podman", "docker"):
            if shutil.which(runtime) is None:
                continue
            cls.runtime = runtime
            try:
                with tempfile.TemporaryDirectory(prefix="clive-probe-") as tmp:
                    cmd = cls.wrap_with(["/bin/true"], Path(tmp), Limits(), is_compile=False)
                    done = subprocess.run(cmd, capture_output=True, timeout=30)
                if done.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
            cls.runtime = None
        return False
