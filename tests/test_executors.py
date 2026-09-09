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


def test_container_compile_step_gets_no_memory_or_pids_cap():
    """base.py's Limits.compile_seconds docstring: gcc "is never given memory_mb: the
    compiler routinely needs more than a student's program is allowed, and an
    RLIMIT_AS that killed gcc would surface as a compile error on correct code."
    LocalExecutor/BwrapExecutor keep this promise by passing preexec=None to the
    compile-step spawn; the container backend's equivalent is to never pass
    --memory/--pids-limit to the compile-step container at all, and to derive its
    --timeout from compile_seconds rather than run_seconds. This is a pure argv
    inspection -- it needs no podman/docker install and runs unconditionally.
    """
    from pathlib import Path

    from clive.executors.container import ContainerExecutor

    ContainerExecutor.runtime = "podman"
    limits = Limits(compile_seconds=37, run_seconds=5)
    workdir = Path("/tmp/does-not-need-to-exist")

    compile_cmd = ContainerExecutor.wrap_with(
        ["gcc", "-o", "program", "main.c"], workdir, limits, is_compile=True,
    )
    assert "--memory" not in compile_cmd
    assert "--pids-limit" not in compile_cmd
    assert compile_cmd[compile_cmd.index("--timeout") + 1] == str(limits.compile_seconds + 5)

    run_cmd = ContainerExecutor.wrap_with(
        ["./program"], workdir, limits, is_compile=False,
    )
    assert "--memory" in run_cmd
    assert "--pids-limit" in run_cmd
    assert run_cmd[run_cmd.index("--timeout") + 1] == str(limits.run_seconds + 5)


def test_container_compile_timeout_is_not_cut_short_by_run_seconds():
    """Regression, behavioral: before the fix, --timeout for BOTH steps derived from
    run_seconds, so a compile that legitimately takes longer than run_seconds+5 (but
    well within compile_seconds+5) would have been killed by the container's own
    --timeout regardless -- misreporting a still-within-budget compile as failed.

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
    from pathlib import Path

    from clive.executors.container import ContainerExecutor

    limits = Limits(compile_seconds=30, run_seconds=1)
    with tempfile.TemporaryDirectory(prefix="clive-test-") as tmp:
        cmd = ContainerExecutor.wrap_with(
            ["sleep", "10"], Path(tmp), limits, is_compile=True,
        )
        # Wall-clock timeout here is just headroom for the assertion itself, well
        # above the 10s sleep and the container's own ~35s --timeout ceiling would
        # never be reached anyway; it exists only so a genuinely broken invocation
        # cannot hang the test suite.
        done = subprocess.run(cmd, capture_output=True, timeout=20)
    assert done.returncode == 0, done.stderr.decode(errors="replace")
