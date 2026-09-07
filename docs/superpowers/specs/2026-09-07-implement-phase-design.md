# The Implement phase: a C coding interface judged by a compiler

Status: approved, not yet implemented
Date: 2026-09-07

## Why

CLive covers the first three steps of PCDIT — Problem, Cases, Design — because those are
the steps where a judge reads prose. The README has said since the beginning that
"Implement and Test stay with AnimoRank's autograder." This spec brings **Implement**
into CLive.

The point is not to reimplement an autograder. It is that PCDIT's fourth step is the one
where a student's plan meets a compiler, and CLive is the only place that holds the plan.
A plain autograder can tell a student their output is wrong. CLive can tell them their
output is wrong *in the place where their code stopped following the design they wrote in
phase 3* — and it can do that because `prior_artifacts` already carries phases 1-3 into
every later phase's prompt.

So the phase is gated by tests and advised by a judge, and the judge's whole subject is
conformance between the code and the student's own earlier work.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| What gates the phase | Tests gate, judge advises | An LLM must not hold a student back on code that demonstrably works. |
| I/O contract | AnimoRank's `ProgramIOTestCase`: stdin to stdout, exact match | CLive's existing `public_test_cases` are already this shape. |
| Where code runs | Container first, local sandbox fallback | Served from one host to participants; the image also pins the toolchain. |
| Hidden cases | New optional `hidden_test_cases:` | Additive — all nine existing problem files stay valid untouched. |
| Authoring | Studio Problem tab plus Sandbox Session | Keeps the Studio's promise that it can author everything the engine reads. |
| Compile flags | `gcc -Werror -Wall`, warnings shown as a distinct state | Parity with AnimoRank; the distinct state keeps a warning from reading as a wrong answer. |

## What AnimoRank does, and where this diverges

Read from `github.com/iwillreku3206/animorank` at `src/lib/testCase/` and
`src/routes/api/practice-session/[id]/run/+server.ts`.

AnimoRank compiles with `gcc -Werror -Wall -o program *.c -lm -lpthread`, runs `./program`,
and executes through **Judge0** over HTTP (`language_id: 89`, a zip of source plus
`compile` and `run` scripts, 30s limit). Test cases come in three types, each carrying a
`public` flag: `ProgramIOTestCase` (stdin to stdout), `FunctionOutputTestCase` (the
default — a generated `main.c` strips the student's `main()` by regex and calls their
function against typed parameters and comparisons), and `CustomTestCase`. Two run modes:
`public` for Run, `all` for Submit, with non-public results stripped of `runInfo` and
`testCaseInfo` before they leave the server.

Adopted: the compile and run lines, the stdin/stdout contract, the `public`/`all` split,
the server-side stripping of hidden results, `starter_code` on the problem, and the shape
of the executor interface (files plus compile/run scripts plus limits, returning a
discriminated union of compile error / timeout / runtime error / success).

Four deliberate divergences:

1. **Trailing whitespace is normalised before comparison.** AnimoRank compares
   `stdout === dbTestCase.output` strictly. Every problem in `cases/problems/` stores its
   expected output without a trailing newline (`output: '3'`), so a student writing
   `printf("%d\n", count)` produces `"3\n"` and fails. Ported strictly, **all nine existing
   problems would reject correct programs.** The grader therefore compares after stripping
   trailing whitespace from each line and trailing blank lines from the whole. Interior
   whitespace is significant.

2. **Compile once, run N times.** AnimoRank compiles inside each test case's `execute()`,
   so five cases means five Judge0 submissions and five compiles. On a single shared host
   that is five times the cost for no benefit.

3. **5s per run, not 30s.** 30s per case, times N cases, times M concurrent participants on
   one box is a self-inflicted denial of service. Paired with a separate compile timeout, a
   pids cap, a memory cap, and an output cap.

4. **`FunctionOutputTestCase` is not ported.** It is a type-registry and code-generation
   subsystem, and CLive has no problem that needs it: `crowley_path` asks for `solvePath()`
   but its cases are already plain input/output pairs. The function shape is scaffolded
   through `starter_code` instead. The executor interface takes a file *map*, not a single
   source string, so a generated `main.c` can be added later without reopening it.

## 1. Content model

### `cases/problems/<slug>.yaml`

Two new optional keys. Both default to empty, so every existing file remains valid and
`save_problem` round-trips a file that has neither.

```yaml
starter_code: |
  #include <stdio.h>

  int main(void) {
      return 0;
  }

hidden_test_cases:
  - input: "aeiou"
    output: "5"
```

`save_problem` gains `starter_code` and `hidden_test_cases` in its key order, after
`public_test_cases`. `hidden_test_cases` is validated and normalised exactly as
`public_test_cases` is — the same empty-row skipping and the same `\r\n` normalisation —
by extracting the existing loop into a shared helper rather than copying it.

### `prompts/phases/implement.yaml` (new)

```yaml
id: phase.implement
version: 1
phase: implement
label: Implement
order: 4
gate: tests
```

`gate` is a new phase key with two values, `criteria` and `tests`. `load_phase` defaults it
to `criteria`, so the three existing phases are byte-identical and no existing YAML changes.
`save_phase` validates it against the allowed set and places it in the key order after
`order`. This is the single switch that Approach 1 turns on.

`artifact_fields` carries one field:

```yaml
artifact_fields:
  - id: code
    label: Your C program
    kind: code
    language: c
    hint: A complete program. Read from standard input, print to standard output.
```

`kind` is a new artifact-field key defaulting to `text`. Only `code` renders Monaco; every
existing field on every existing phase renders the textarea it renders today. `language` is
advisory metadata for the editor and is only read when `kind` is `code`.

### `criteria/implement.yaml` (new)

Every criterion is `gate: advisory`. This is not a hedge — it is what "tests gate, judge
advises" means, and `student.submit` depends on it: a gating criterion here would let the
judge block code that passes every test, which the design explicitly rules out. The
criteria judge the code against the student's own phases 1-3:

- `follows_own_design` — the code's steps correspond to the ordered plan written in Design
- `state_matches_design` — the variables correspond to the state the student named there
- `handles_own_edge_cases` — the edge cases invented in Cases are handled deliberately
- `readable` — names and structure a person could follow

Written as PASS/FAIL rules in the same form as the existing three files, with `guidance`.

## 2. `src/clive/executors/`

Mirrors `src/clive/providers/` deliberately: one file per backend, a `REGISTRY`, an
environment variable to pick, and vendor imports deferred inside the call so importing the
package stays cheap. An author reading `providers/` already knows how to read this.

```
src/clive/executors/__init__.py   REGISTRY, get_executor(), probe order
src/clive/executors/base.py       Executor ABC, request and result types, Limits
src/clive/executors/container.py  podman, then docker
src/clive/executors/local.py      bwrap when usable, else bare POSIX rlimits
```

### The interface (`base.py`)

```python
@dataclass(frozen=True)
class Limits:
    compile_seconds: int = 10
    run_seconds: int = 5
    memory_mb: int = 256
    pids: int = 64
    output_bytes: int = 64 * 1024

@dataclass(frozen=True)
class ExecutionRequest:
    files: dict[str, str]       # filename -> contents; the student's program is main.c
    compile_argv: list[str]
    run_argv: list[str]
    stdins: list[str]           # one per case: compile once, run len(stdins) times
    limits: Limits
```

The result mirrors AnimoRank's `CodeExecutionResponse` as a discriminated union. A
compile failure carries the compiler's stderr and no runs; otherwise every stdin gets a
`RunOutcome` whose `status` is one of `ok`, `timeout`, `runtime_error`, or
`output_truncated`, alongside `stdout`, `stderr`, `exit_code`, and `duration_ms`.
`CompileOutcome` additionally carries `warnings` — the compiler's stderr when compilation
*succeeded* — which is what makes the distinct warning state possible.

`Executor` is an ABC with `name`, `isolation` (`"container" | "namespace" | "rlimit"`),
a classmethod `probe() -> bool` reporting whether this backend can actually run here, and
`execute(request) -> ExecutionResult`. Every backend translates its own failures into an
`ExecutorError` rather than leaking a subprocess exception, exactly as a `Provider`
translates SDK failures into `JudgeError`.

### Selection

`get_executor()` resolves in order: an explicit `CLIVE_EXECUTOR` name, else the first
backend in probe order whose `probe()` returns true — container (podman, then docker),
then local-bwrap, then local-posix. `CLIVE_SANDBOX_FLOOR` names the weakest acceptable
isolation and `get_executor()` raises rather than returning something below it; on a host
serving several participants this should be set. Probe results are cached for the process.

`probe()` must be cheap and must not assume: bwrap exists on this machine but is not
setuid, and unprivileged user namespaces are restricted by AppArmor on Ubuntu 23.10+ and
were disabled by default on older Debian. So the bwrap probe runs an actual
`bwrap --unshare-all --die-with-parent /bin/true` and believes the exit code, rather than
testing for the binary.

### The container backend

```
podman run --rm --network none --read-only --tmpfs /tmp:size=64m
           --memory 256m --pids-limit 64 --cpus 1
           --volume <workdir>:/work:rw --workdir /work
           docker.io/library/gcc:14 <argv>
```

The work directory is mounted **read-write**: gcc writes `program` into it, and the run
step then executes that binary. `--read-only` still applies to the container's own root
filesystem, so the only writable paths are the per-request work directory and the private
`/tmp`. Both are discarded when the request ends.

The image pins gcc, which is the reason this is the default: it is the only backend under
which two participants on two machines are guaranteed the same verdict for the same code.
`CLIVE_EXECUTOR_IMAGE` overrides it. Docker is tried with the same flags when podman is
absent.

### The local backend

bwrap with `--unshare-all --die-with-parent`, `/usr` and `/etc` read-only, `--proc`,
`--dev`, a private `--tmpfs /tmp`, and the work directory bound **read-write** — gcc must
write `program` into it — plus `setrlimit` for `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NPROC`,
and `RLIMIT_FSIZE` in a `preexec_fn`. Without bwrap, the rlimits and the timeout stand
alone and `isolation` is `"rlimit"` — honest about giving no network or filesystem
isolation, which is what `CLIVE_SANDBOX_FLOOR` exists to refuse.

`Limits.memory_mb` governs the **run** step only. gcc regularly needs more than a
student's program is allowed, and an `RLIMIT_AS` of 256 MB applied to the compiler would
surface as a compile error on correct code. The compile step is bounded by
`compile_seconds` and by the sandbox, not by the run-time memory cap.

Every run starts a new session (`os.setsid`) so a timeout kills the whole process group
with `killpg`, not just the direct child. A child that survives `SIGTERM` gets `SIGKILL`.

### Concurrency

A module-level `threading.BoundedSemaphore(CLIVE_MAX_CONCURRENT_RUNS)`, default 4, held
across the compile and all runs of one request. `ThreadingHTTPServer` spawns a thread per
request and would otherwise start an unbounded number of compiles under load.

## 3. `src/clive/grade.py`

The seam between a problem and an executor. Pure data in, pure data out, no HTTP, no
filesystem — so the Studio's Sandbox can grade a scratch problem exactly as `/student`
grades a saved one, which is the same property `judge()` already has.

```python
def grade(problem: dict, code: str, scope: Literal["public", "all"]) -> dict
```

Assembles the case list (`public_test_cases`, plus `hidden_test_cases` when scope is
`all`), builds one `ExecutionRequest` with `main.c` set to the student's code, calls the
executor once, and compares.

Returns:

```python
{
  "compiled": bool,
  "compile_error": str,        # gcc stderr; "" when compiled
  "warnings": str,             # gcc stderr when it compiled anyway; "" when clean
  "passed": bool,              # compiled and every case in scope passed
  "counts": {"passed": int, "failed": int, "total": int},
  "cases": [ ... ],
  "executor": {"name": str, "isolation": str},
}
```

A public case reports `{"hidden": False, "input", "expected", "actual", "status",
"passed", "duration_ms"}`. A hidden case reports `{"hidden": True, "passed": bool,
"status": str}` and nothing else — no input, no expected, no actual. The stripping happens
here rather than in the route, because AnimoRank does it in its route and that is one
forgetful caller away from a leak; below the route, no caller can forget.

Comparison is the normalisation described under divergence 1, applied to both sides.

## 4. Student API

### `POST /api/student/run` (new)

Body `{problem_id, code}`. Returns `grade(problem, code, scope="public")`. No judge, no
nudge, no attempt counter, no rubric. This is the Run button: fast, free, and repeatable,
and it is the only new route the page needs.

### `POST /api/student/submit` (extended)

Branches on `phase.get("gate")`:

- **`criteria`** — the existing three phases. The code path is untouched.
- **`tests`** — grade at `scope="all"`.
  - Any case fails, or compilation fails: return `test_run` plus a nudge computed from the
    failing tests. **The judge is not called.** There is no value in spending a model call
    reviewing code that does not work, and it means the advisory judge only ever reads
    working code. `passed` is false; the attempt counter increments.
  - Everything passes: call `judge()` for the advisory criteria and return `test_run`
    alongside the usual `verdicts`. `passed` is true regardless of the advisory verdicts,
    which is what advisory means.

The response keeps its existing keys and adds `test_run`. `blocking` stays empty for a
tests-gated phase — a failing test is not a criterion — so nothing downstream mistakes a
wrong answer for a rubric failure.

### `boot()`

Gains `executor: {"available": bool, "name": str, "isolation": str, "toolchain": str}`,
so the page can disable Run with an honest message instead of failing on click, and so a
verdict can be traced to the toolchain that produced it.

### `problem()`

Gains `starter_code`. It must **never** gain `hidden_test_cases`. This is the same class of
rule as "the rubric is not sent until it has been ruled on", and it gets the same treatment:
enforced in `student.py`, asserted in `tests/test_student.py`, against both the JSON and the
served HTML.

## 5. `prompts/base/nudge_code.yaml`

Its own base document, beside `hint.yaml`, `nudge.yaml`, and `personas.yaml`. A failing test
is a different shape from a failing criterion, and `nudge()` already refuses to run without
failing gates — which a tests-gated phase, having only advisory criteria, will never have.

`nudge_code()` in `src/clive/nudge.py` renders it. It receives the problem, the student's
code, the failing **public** cases with their input, expected and actual, the compile error
when there is one, and `prior_artifacts` carrying phases 1-3. It receives only a *count* of
failing hidden cases, never their inputs — the hidden-case rule holds inside the prompt as
well as in the response.

Its job is the one thing a plain autograder cannot do: point at the discrepancy between the
code and the plan the student already wrote. "Your Design says the counter resets on each
pass; the loop resets it once, before the loop." It names the gap and never supplies the
fix, which is the doctrine `nudge.yaml` and `hint.yaml` already share.

The output reuses the existing `Nudge` pydantic model and its schema, so the page renders it
through the component that already exists. `focus_id` carries the zero-based index of the failing public case as a string
(`"0"`, `"2"`), or `"compile"` when compilation failed, rather than a criterion id; the
renderer already treats it as an opaque key.

## 6. The student page

Monaco is loaded from CDN as ESM (`monaco-editor` `min/vs` loader, `cpp` language
contribution), themed from the CSS custom properties already defined in `student.html` so it
matches both the light and dark palettes rather than shipping a third colour scheme.

The artifact-field loop gains one branch: `kind === "code"` mounts an editor, everything else
renders today's textarea. The editor seeds from `starter_code` on first visit and persists to
`localStorage` with the rest of the artifact, so a reload does not lose work — the same
guarantee every other field already has.

Below the editor: **Run** (public cases, no attempt spent) and **Submit for checking** (all
cases, then the judge). A results panel renders one row per case — input, expected, actual and
a status badge for public cases; a bare pass/fail badge for hidden ones. A compile failure
replaces the rows with gcc's stderr, verbatim, in a monospace block. Warnings render as their
own state above the results, not as a failure.

## 7. Studio

- **Problem tab** — a `starter_code` editor (the same Monaco module, so it is written once)
  and a hidden-cases table beside the public one, visually distinguished so an author cannot
  mistake which list they are filling in.
- **Sandbox Session** — gains the Implement phase, grading against the sandbox's scratch copy
  of the problem, so a rehearsal covers all four phases.
- **Rubric tab** — picks up `implement`'s advisory criteria with no change; it already groups
  by phase and reads whatever `list_phases()` returns.

## 8. Testing

- `tests/test_executors.py` — a known-good program, a compile error, a warning that still
  compiles, a timeout, an infinite loop, a memory hog, an output flood, and a program that
  forks. Parametrised over every backend whose `probe()` passes, and skipped entirely when
  none does, so the suite stays green on a machine with no compiler.
- `tests/test_grade.py` — comparison semantics including the trailing-newline rule, hidden
  stripping, scope selection, and the counts. Against a stub executor: no subprocess, no
  network, fast.
- `tests/test_student.py` — extended with the new invariant: `hidden_test_cases` reach
  neither `problem()` nor the served HTML. The existing rubric-leak assertions cover
  `criteria/implement.yaml` automatically, since they iterate every phase in the repo.
- `tests/test_prompts.py` additions — `gate` defaults to `criteria` on a phase that omits it;
  `save_phase` rejects an unknown gate; `save_problem` round-trips a file with neither new key.

## 9. Risks

- **Toolchain drift.** The local fallback uses whatever gcc is on the host, the container
  pins one. The same code can earn different verdicts. Mitigated by reporting the toolchain
  in `boot()` and documenting the container as the default, not eliminated.
- **Monaco from CDN.** No offline use, and a CDN outage disables the editor. Acceptable
  because the app is already served over a network to participants and already loads fonts
  from a CDN; vendoring is a later change confined to one file.
- **`-Werror` fails correct programs.** An unused variable is a failed build. Kept for
  parity with AnimoRank, with warnings rendered as a distinct state so a student is not told
  their answer is wrong when it is not. Reversing this is one flag in one phase file.
- **No user model.** Serving several participants from one host with sessions in
  `localStorage` means no per-student rate limiting is possible above the global semaphore.
  A participant who reloads loses nothing, but two participants cannot be told apart. This is
  a pre-existing property of CLive, surfaced rather than introduced by this work.

## Out of scope

`FunctionOutputTestCase` and its type registry; the Test phase of PCDIT (the fifth step);
a Judge0 executor backend (the interface admits one as a single new file plus a `REGISTRY`
entry, and that is the whole point of the abstraction); per-student identity and rate
limiting; languages other than C.
