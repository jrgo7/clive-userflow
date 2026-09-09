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
