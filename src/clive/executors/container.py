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
    def preexec_for_run(limits: Limits, nproc_ceiling: int):
        """None: the limits below are the container's, and applying them to the client
        process instead would cap podman rather than the student's program."""
        return None

    @classmethod
    def wrap_with(cls, argv: list[str], workdir: Path, limits: Limits) -> list[str]:
        return [
            cls.runtime, "run", "--rm",
            # Without this, podman leaves the container's stdin closed (EOF)
            # regardless of what the client writes to the pipe -- a program that
            # calls scanf() would see immediate EOF rather than the intended input.
            "--interactive",
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
