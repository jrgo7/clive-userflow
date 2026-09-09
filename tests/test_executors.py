"""The sandbox backends, exercised against real C.

Every test here compiles and runs actual code, so the whole module skips on a host
with no working backend -- a machine without a compiler should not fail the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clive import config
from clive.executors import ExecutorError, available_executors
from clive.executors.base import ExecutionRequest, Limits
from clive.executors.container import ContainerExecutor

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
    assert result.runs[0].status == "output_truncated"


def test_unbounded_flood_is_capped_promptly_not_after_the_full_timeout(executor):
    """Regression test: a program that never stops producing output must be killed as
    soon as `output_bytes` is exceeded, not drained until it hits EOF (impossible
    here) or the full `run_seconds` wall clock -- the previous implementation
    buffered the flood into memory via a blocking `communicate()` and only checked
    `output_bytes` afterward, so it always paid the full timeout (and, decoding
    everything it had buffered by then, sometimes noticeably more).
    """
    source = """
#include <stdio.h>
int main(void) { for (;;) printf("flood\\n"); return 0; }
"""
    result = executor.run(request_for(source, ["1"], output_bytes=4096, run_seconds=8))
    assert result.compiled, result.compile_error
    run = result.runs[0]
    assert run.status == "output_truncated"
    assert len(run.stdout) <= 4096
    # Generous relative to the ~20ms actually observed -- the point is "nowhere near
    # the 8000ms timeout", not a tight latency bound this test would flake on.
    assert run.duration_ms < 2000


def test_large_stdin_against_a_non_reading_flooding_child_does_not_deadlock(executor):
    """Regression test: writing stdin must never be a blocking step that happens
    before the read loop starts. A child that floods stdout while never reading
    stdin at all (no `scanf`) can leave the parent's stdin pipe full after ~64 KiB --
    if that write sits outside the loop that enforces `run_seconds`, the parent
    blocks on it forever, deadlocked against the child's own full, undrained stdout
    pipe, and `run_seconds` never gets a chance to fire.
    """
    big_stdin = "x" * (200 * 1024)  # comfortably over a 64 KiB pipe buffer
    source = """
#include <stdio.h>
int main(void) { for (;;) printf("flood\\n"); return 0; }
"""
    result = executor.run(request_for(source, [big_stdin], output_bytes=4096, run_seconds=3))
    assert result.compiled, result.compile_error
    run = result.runs[0]
    assert run.status == "output_truncated"
    assert len(run.stdout) <= 4096
    # The real point of this test is that it returns at all -- a deadlocked
    # implementation never reaches this line. Generous relative to the low tens of
    # ms actually observed, but well inside run_seconds=3.
    assert run.duration_ms < 2000


def test_a_crash_is_a_runtime_error_not_an_exception(executor):
    source = "int main(void) { int *p = 0; *p = 1; return 0; }"
    result = executor.run(request_for(source, ["1"]))
    assert result.runs[0].status == "runtime_error"


def test_fork_succeeds_under_default_pids_limit(executor):
    """A correct fork() must not fail just because the host already has other,
    unrelated processes and threads running under the same user -- `limits.pids` is
    a budget above ambient load, not an absolute ceiling on it.
    """
    source = """
#include <unistd.h>
#include <sys/wait.h>
int main(void) {
    pid_t pid = fork();
    if (pid < 0) { return 1; }
    if (pid == 0) { _exit(0); }
    int status;
    waitpid(pid, &status, 0);
    return 0;
}
"""
    result = executor.run(request_for(source, ["1"]))
    assert result.compiled, result.compile_error
    assert result.runs[0].status == "ok"
    assert result.runs[0].exit_code == 0


def test_isolation_is_reported_honestly(executor):
    """A backend must not claim isolation it does not provide -- CLIVE_SANDBOX_FLOOR
    is enforced against this string and nothing else."""
    assert executor.isolation in ("container", "namespace", "rlimit")


def test_workdir_bytes_sums_regular_files_recursively(tmp_path):
    from clive.executors.local import _workdir_bytes

    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.txt").write_bytes(b"y" * 250)
    assert _workdir_bytes(tmp_path) == 350


def test_workdir_bytes_survives_a_file_that_vanishes_mid_walk(tmp_path):
    """Best-effort, by design: a file gone between the walk and the stat -- the
    student's own program cleaning up after itself, say -- must not turn a disk-usage
    check into a crash."""
    from clive.executors.local import _workdir_bytes

    gone = tmp_path / "gone.txt"
    gone.write_bytes(b"z" * 10)
    gone.unlink()
    assert _workdir_bytes(tmp_path) == 0


FLOOD_TO_DISK = """
#include <stdio.h>
int main(void) {
    FILE *f = fopen("flood.bin", "wb");
    if (!f) return 1;
    char buf[1 << 20] = {0};   /* 1 MiB */
    for (int i = 0; i < 4; i++) {
        if (fwrite(buf, 1, sizeof buf, f) != sizeof buf) break;   /* stop at RLIMIT_FSIZE */
    }
    fclose(f);
    printf("done\\n");
    return 0;
}
"""


def test_a_large_disk_write_is_never_reported_ok(executor):
    """No backend may report `ok` for a run that wrote far more to its work
    directory than a reasonable program would need.

    local/local-bwrap catch this hard, at the kernel level: RLIMIT_FSIZE is applied
    straight to the student's process (`_rlimits` in local.py), so the write itself
    fails with SIGXFSZ partway through and the run is a `runtime_error`. The
    container backend has no such rlimit -- a Python rlimit would cap the
    podman/docker client, not the containerized program (see
    `ContainerExecutor.preexec_for_run`) -- and used to report this `ok`
    (verified empirically: a container run that wrote 20 MiB to its work directory
    succeeded outright). `workdir_bytes` on `Limits`, checked once after every run
    in `LocalExecutor.execute`, is the best-effort mitigation: not a hard cap (the
    bytes can still land on host disk within the run's own time budget), only a
    guarantee that a run which wrote this much is never misreported as `ok`.
    """
    result = executor.run(request_for(FLOOD_TO_DISK, ["1"], workdir_bytes=2 * 1024 * 1024))
    assert result.compiled, result.compile_error
    assert result.runs[0].status != "ok"
    assert result.runs[0].status in ("runtime_error", "disk_exceeded")


def test_container_disk_flood_is_caught_by_workdir_bytes_specifically():
    """The regression this fixes, narrowly: on the container backend alone (the one
    backend with no RLIMIT_FSIZE), a disk flood must be caught by the `workdir_bytes`
    post-hoc check specifically, not merely "by something" as the test above allows.
    """
    if "container" not in [e.name for e in EXECUTORS]:
        pytest.skip("container backend not available on this host")
    result = ContainerExecutor().run(
        request_for(FLOOD_TO_DISK, ["1"], workdir_bytes=2 * 1024 * 1024)
    )
    assert result.compiled, result.compile_error
    assert result.runs[0].status == "disk_exceeded"


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


@pytest.fixture
def podman_runtime(monkeypatch):
    """Sets ContainerExecutor.runtime for one test, then restores whatever `probe()`
    actually found on this host.

    Without the restore, a test that assigns `ContainerExecutor.runtime = "podman"`
    directly (as this module used to) permanently clobbers the class attribute for
    every later container test in the same process -- on a docker-only host that
    silently makes every subsequent real-container test try to invoke a `podman`
    that is not there. `monkeypatch.setattr` undoes it automatically at teardown,
    whatever the test does in between.
    """
    monkeypatch.setattr(ContainerExecutor, "runtime", "podman")


def test_container_compile_step_gets_no_memory_or_pids_cap(podman_runtime):
    """base.py's Limits.compile_seconds docstring: gcc "is never given memory_mb: the
    compiler routinely needs more than a student's program is allowed, and an
    RLIMIT_AS that killed gcc would surface as a compile error on correct code."
    LocalExecutor/BwrapExecutor keep this promise by passing preexec=None to the
    compile-step spawn; the container backend's equivalent is to never pass
    --memory/--pids-limit to the compile-step container at all, and to derive its
    in-container `timeout` from compile_seconds rather than run_seconds. This is a
    pure argv inspection -- it needs no podman/docker install and runs unconditionally.
    """
    limits = Limits(compile_seconds=37, run_seconds=5)
    workdir = Path("/tmp/does-not-need-to-exist")

    compile_cmd = ContainerExecutor.wrap_with(
        ["gcc", "-o", "program", "main.c"], workdir, limits, is_compile=True,
    )
    assert "--memory" not in compile_cmd
    assert "--pids-limit" not in compile_cmd
    i = compile_cmd.index("timeout")
    assert compile_cmd[i : i + 4] == ["timeout", "-k", "1", str(limits.compile_seconds + 5)]
    assert compile_cmd[i + 4 :] == ["gcc", "-o", "program", "main.c"]

    run_cmd = ContainerExecutor.wrap_with(
        ["./program"], workdir, limits, is_compile=False,
    )
    assert "--memory" in run_cmd
    assert "--pids-limit" in run_cmd
    j = run_cmd.index("timeout")
    assert run_cmd[j : j + 4] == ["timeout", "-k", "1", str(limits.run_seconds + 5)]


@pytest.mark.parametrize("runtime", ["podman", "docker"])
def test_wrap_with_never_passes_a_runtime_specific_timeout_flag(runtime, monkeypatch):
    """Regression for the Critical bug this fixes: podman's `run` accepts a
    `--timeout` flag, docker's does not ("unknown flag: --timeout", exit 125,
    verified empirically) -- so passing it unconditionally made every compile fail
    on a docker-only host, on the strongest isolation tier, reported to the student
    as a compile error on correct code. Neither runtime should ever see it now: the
    wall clock is enforced by wrapping the in-container command with coreutils' own
    `timeout` instead, identically for both, so this must hold for `docker` even
    though this suite may only ever run on a `podman` host.
    """
    monkeypatch.setattr(ContainerExecutor, "runtime", runtime)
    limits = Limits(compile_seconds=37, run_seconds=5)
    workdir = Path("/tmp/does-not-need-to-exist")

    for is_compile in (True, False):
        cmd = ContainerExecutor.wrap_with(["gcc"], workdir, limits, is_compile=is_compile)
        assert "--timeout" not in cmd
        assert cmd[0] == runtime
        image_index = cmd.index(config.EXECUTOR_IMAGE)
        assert cmd[image_index + 1 : image_index + 3] == ["timeout", "-k"]


def test_wrap_with_refuses_to_build_a_command_with_no_probed_runtime(monkeypatch):
    """`ContainerExecutor` built without a prior `probe()` call must fail with the
    `ExecutorError` every backend's docstring promises, not a bare `TypeError` from
    `subprocess.Popen([None, ...])` -- the failure a caller that skips `get_executor()`
    (which always probes) would otherwise hit.
    """
    monkeypatch.setattr(ContainerExecutor, "runtime", None)
    with pytest.raises(ExecutorError):
        ContainerExecutor.wrap_with(["./program"], Path("/tmp"), Limits(), is_compile=False)


def test_probe_actually_runs_a_container_not_just_checks_the_image():
    """The container counterpart of `BwrapExecutor.probe`'s own test below: probing
    must exercise `wrap_with`'s actual output by actually running it, so a
    runtime-specific flag mismatch (the Critical bug fixed here) fails `probe()`
    itself rather than silently passing and only then failing every real compile.
    """
    if "container" not in [e.name for e in EXECUTORS]:
        pytest.skip("no container runtime on this host")
    assert ContainerExecutor.probe() is True
    assert ContainerExecutor.runtime in ("podman", "docker")


def test_container_compile_timeout_is_not_cut_short_by_run_seconds():
    """Regression, behavioral: before the fix, the container's timeout for BOTH steps
    derived from run_seconds, so a compile that legitimately takes longer than
    run_seconds+5 (but well within compile_seconds+5) would have been killed
    regardless -- misreporting a still-within-budget compile as failed.

    A real gcc compile is too fast to distinguish the two timeouts reliably, so this
    runs `wrap_with`'s own compile-shaped argv directly with `sleep` standing in for
    a slow compile: with run_seconds tiny (timeout would be ~6s if the bug were still
    present) and compile_seconds generous (timeout ~35s), a process that takes 10s
    must survive -- proving the container timeout actually came from
    compile_seconds, not run_seconds.
    """
    if "container" not in [e.name for e in EXECUTORS]:
        pytest.skip("container backend not available on this host")
    import subprocess
    import tempfile

    limits = Limits(compile_seconds=30, run_seconds=1)
    with tempfile.TemporaryDirectory(prefix="clive-test-") as tmp:
        cmd = ContainerExecutor.wrap_with(
            ["sleep", "10"], Path(tmp), limits, is_compile=True,
        )
        # Wall-clock timeout here is just headroom for the assertion itself, well
        # above the 10s sleep -- the container's own ~35s timeout ceiling would never
        # be reached anyway; it exists only so a genuinely broken invocation cannot
        # hang the test suite.
        done = subprocess.run(cmd, capture_output=True, timeout=20)
    assert done.returncode == 0, done.stderr.decode(errors="replace")


def test_container_run_timeout_actually_fires_from_inside_the_container():
    """Behavioral: the in-container `timeout` wrapper that replaced the CLI
    `--timeout` flag must still bound a runaway run step -- self-enforced from
    inside the container's own PID namespace, so this holds even if the client
    process that launched `podman run`/`docker run` were killed first.

    Uses whatever runtime `available_executors()` actually probed at module load
    (not the `podman_runtime` fixture), because this spawns a real container and a
    forced runtime the host does not have would fail for the wrong reason.
    """
    if "container" not in [e.name for e in EXECUTORS]:
        pytest.skip("container backend not available on this host")
    import subprocess
    import tempfile
    import time

    limits = Limits(run_seconds=2)
    with tempfile.TemporaryDirectory(prefix="clive-test-") as tmp:
        cmd = ContainerExecutor.wrap_with(["sleep", "60"], Path(tmp), limits, is_compile=False)
        started = time.monotonic()
        done = subprocess.run(cmd, capture_output=True, timeout=30)
        elapsed = time.monotonic() - started
    # 124 is GNU coreutils' `timeout` exit status when it had to kill the command.
    assert done.returncode == 124, done.stderr.decode(errors="replace")
    assert elapsed < 15, "the in-container timeout did not fire promptly"
