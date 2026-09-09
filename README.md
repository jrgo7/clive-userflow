# CLive User Flow

This repository outlines and demonstrates the various steps in CLive's user flow.
CLive aims to adopt the PCDIT framework for solving programming problems as an extension
module for AnimoRank (an open-source programming practice platform).

There are three ways in: a set of Jupyter notebooks that walk through the mechanics of a
judging call, **CLive Studio**, a local app for authoring the things those calls run on,
and the **student view** at `/student`, which is the same engine seen from the other side.

## CLive Studio

```bash
uv sync
cp .env.example .env      # then paste your ANTHROPIC_API_KEY
uv run clive-studio       # opens http://127.0.0.1:8765
```

`--port N` to move it, `--no-browser` to stop it opening a window. Editing works without
an API key; only the Run tab needs one. The same server also serves the student view at
`http://127.0.0.1:8765/student` — **Student view** in the header opens it.

> **Deployment warning: the Studio API has no authentication.** Every route under
> `/api/`, including `GET /api/problem/<slug>` (which returns a problem's
> `hidden_test_cases` in full) and every criteria/prompt file the Studio can edit, is
> served to whoever can reach the port — there is no login, no token, nothing. It
> defaults to loopback-only (`127.0.0.1`), which is safe on your own machine, but if
> you bind it to a real interface or put it behind a tunnel or a reverse proxy without
> adding your own auth layer (a proxy that requires a login, a firewall rule, an SSH
> tunnel — anything), anyone who can reach the port can read the rubric and every
> hidden test case for every problem. Do not expose this server to an untrusted
> network as-is.

**Provider.** The judge call goes to Anthropic by default. Set `CLIVE_PROVIDER=deepseek`
in `.env` (with `DEEPSEEK_API_KEY`) to send it to DeepSeek instead — the model dropdown and
the key pill follow the choice. DeepSeek has no `effort` or thinking knob; pick
`deepseek-reasoner` in the Prompt tab when you want reasoning. Each provider lives in
`src/clive/providers/`; adding a third is a new file plus a `REGISTRY` entry.

The Studio is a thin editor over the YAML in this repo — every save writes the same file a
human would hand-edit, comments at the top of the file included. Nothing is stored anywhere
else, so the notebooks, the Studio, and `git diff` never disagree.

| Tab | Edits | Writes to |
|---|---|---|
| **Rubric** | Read-only. Every criterion in every phase, with its current PASS/FAIL status, grouped by phase | nothing |
| **Criteria** | The rubric for the selected phase — add, edit, reorder, delete, and version each PASS/FAIL rule | `criteria/<phase>.yaml` |
| **Problem** | Problem statements and their public test cases; create and delete problems | `cases/problems/<slug>.yaml` |
| **Prompt** | The system prompt, the Jinja user template, the student-facing task description, the model/effort/token settings, and the artifact fields the student submits — with a render preview that costs nothing | `prompts/phases/<phase>.yaml` |
| **Run** | A student artifact for the selected phase, judged against the saved criteria in one call | nothing |
| **Simulate** | An LLM persona walks the whole session while you watch — see below | nothing |
| **Personas** | Read-only: every persona, and the exact prompt it would be sent | nothing |

The phase strip at the top switches between the four phases. Run reports each verdict with
its evidence quote, and flags a quote that does not actually appear in the artifact — the
prompt demands verbatim quotation, so a quote that cannot be found means the judge asserted
rather than observed.

## The Rubric tab

Criteria are otherwise only visible one phase at a time. The **Rubric** tab lists all of them
together with the verdict each one currently carries, and the header shows a running
`7/12 passing` tally that follows you across every tab — click it to jump there.

Status comes from the last judged run **for the problem you have selected**, and file-mode and
sandbox verdicts live in separate stores, so an experiment against a gutted rubric is never
mistaken for the real thing. The tab says which set it is showing.

A criterion reads one of four ways:

| | |
|---|---|
| **PASS** / **FAIL** | The verdict from the last run, still trustworthy |
| **STALE** | Judged, but the criterion has been reworded since — the verdict is for text the judge never saw |
| **—** | Never judged, or added to the rubric after the last run |

Staleness is decided by hashing each criterion's `text` and `guidance` at judge time and
re-checking it when the view renders — **not** by `criteria_version`. The version is a label a
human maintains and can be bumped without a wording change or changed without a bump; the hash is
a fact about what the judge was actually given. So bumping the version leaves verdicts valid, and
editing a word of guidance invalidates them even if you forget to bump.

## Simulating a student

The **Simulate** tab runs an LLM through the whole session as a student, streaming each
step as it happens. The judge, the nudge and the phase gating are the real ones running
against the saved criteria — only the student is synthetic. It answers the questions about
a rubric that are otherwise expensive to answer: does a thin answer get blocked for the
reason you intended, does the nudge point somewhere that helps, does a competent answer
actually get through, and does a phase take two attempts or six.

Six characters live in `prompts/base/personas.yaml`, each built to trip something specific:

| Persona | Built to stress |
|---|---|
| **The careful one** (`diligent`) | Nothing — it is the control. If it cannot pass, the rubric is too harsh and nothing the others tell you is worth reading yet |
| **The one-liner** (`minimalist`) | Criteria that ask for substance rather than presence |
| **The restater** (`copier`) | Criteria that ask for the student's own understanding |
| **The one who wants to code** (`code_first`) | Criteria that keep a phase in plain language |
| **The one who does not check** (`confident_wrong`) | Shown working, and expected outputs a judge has to compute to rule on |
| **The one who does not read the note** (`feedback_deaf`) | Whether the nudge escalates, repeats itself, or eventually points somewhere new |
| **The one who is completely lost** (`utter_beginner`) | Everything at once — thin, inconsistent work from someone who does not yet know what the phase is asking. The hardest case, and the most realistic |
| **The one who nods along** (`nods_along`) | The same competence with the help button off, and inarticulate with it — so it separates "did not understand" from "could not say it". Pair it with `utter_beginner` to see what the hint is worth |

**The persona never sees the criteria.** `render_persona_prompt` takes no rubric argument,
so no caller can pass one — a simulated student handed the rubric writes to the rubric, and
the run then measures the rubric against itself. It does see the verdicts and the nudge from
its own previous attempt, because that is what a real student has on screen.

**Reading a run.** The phase `task_description` spells out 11 of the 12 gating criteria
as instructions, because that is what a student should be told. The side effect is that a
model which simply follows those instructions passes the rubric whatever character it was
handed — so if a persona sails through phases it was built to fail, suspect the persona
layer losing to the instruction list before you suspect the rubric. `personas.yaml` v3
addresses this directly in the system prompt; a weaker or lower-effort model also plays a
weak student more convincingly than a strong one.

**A persona can press the help button.** `help_seeking` on each one is `never`,
`when_stuck` (after a failed attempt) or `eager` (before writing anything, which is the
empty-form case the hint was built for). The loop calls the real `hint()`; only its prose
reaches the character, never the criterion it points at — a persona that could read the
rule would satisfy it, and the run would report the hint as more use than it is.

A phase that is never passed stops the run, exactly as it would for a real student. Every
attempt is up to three model calls (write, judge, nudge) plus one more if the persona asks
for help, so the tab estimates the worst case before you start; `attempts` is capped at
`simulate.MAX_ATTEMPTS_CAP`.

The **Personas** tab is read-only and shows each character, its `help_seeking` mode, and —
the part a template cannot show you — the exact prompt it would be sent, rendered against
the selected phase and problem without spending a token. Toggle between the first attempt
and the retry to see the feedback and help blocks.

Add a persona by appending to `personas` in that file — `behaviour` is written as an
instruction to an actor, and `blurb` should name what you expect it to trip.

## The student view

`/student` is what a student sees: the problem, one phase at a time, and the feedback. No
rubric editor, no prompt preview, no model or token readouts. It is not the Sandbox — that is
the author rehearsing a session against a scratch copy of the rubric. This judges the **saved**
files, and its restrictions live in `src/clive/studio/student.py` rather than in the page:

- **The rubric is not sent until it has been ruled on.** `/api/student/boot` returns phases
  without their criteria; a criterion's text reaches the browser only attached to a verdict on
  it. Shipping the rubric and hiding it in the page would leave the checklist one view-source
  away from the student it is meant to make think. `tests/test_student.py` asserts this against
  every criterion in the repo, the served HTML included — a criterion id in a *comment* fails it.
- **Prompts, model ids and token counts are stripped.** They are the author's concern, and they
  invite a student to argue with the judge rather than with the problem.
- **The nudge is not a separate request.** `/api/student/submit` runs it in the same call
  whenever a gate failed, so no page can render a failure without the guidance meant to come
  with it. A nudge that fails comes back as `nudge_error` beside verdicts that still stand.

Feedback reads in three colours, not two: **Met**, **Blocks** (a gating FAIL, which costs an
attempt), and **Depth** (an advisory FAIL, which is reported and never blocks). The session
lives in the browser's `localStorage`, keyed by problem — this system has no user model yet.

## The Implement phase

The fourth phase is the first whose gate is not a judge. The student writes C in an
editor, **Run** checks it against the examples they were given, and **Submit** checks it
against those plus `hidden_test_cases` — cases the student has never seen, which
`student.problem()` never sends to the browser in the first place. Every case must pass;
the model gets no vote on that.

Once it passes, the code is judged once more against the student's own Problem, Cases and
Design — not for bugs, which the tests have already settled, but for whether the program
is the plan. Every criterion in `criteria/implement.yaml` is advisory and
`tests/test_implement_content.py` fails the suite if one is not: a gating criterion there
would let the judge bar code that demonstrably works.

**A failing submission is not judged at all.** It is nudged instead, by
`prompts/base/nudge_code.yaml`, which sees the code, the failing public cases, and the
student's design — so it can say where the program stopped following the plan rather than
restating the diff the page already shows.

**Where the code runs.** `src/clive/executors/` mirrors `src/clive/providers/` for the
registry and the environment variable that picks a backend, but not file-for-file:
`local.py` holds two executors, bare and bubblewrap, because they differ only in how they
wrap the command. `get_executor()` probes and takes the strongest that works — a container
(podman or docker, with the image pinning gcc), then bubblewrap, then bare rlimits — and
`CLIVE_SANDBOX_FLOOR` refuses anything weaker than you specify. Set it to `namespace` or
better on a host serving more than one person. `bwrap`'s probe runs bubblewrap rather than
testing for the binary, because it can be installed and still fail where unprivileged user
namespaces are restricted — and the container backend's probe actually runs a container
the same way, for the same reason: it is what caught a Critical bug where podman's CLI
accepts `--timeout` on `run` and docker's does not, which meant every compile failed on a
docker-only host despite the image being present and correct.

**Known gap: disk usage on the container backend is a post-hoc check, not a hard cap.**
`local`/`local-bwrap` bound how much a student's program can write with `RLIMIT_FSIZE`,
applied straight to the process — the write itself fails once it is exceeded. The
container backend has no equivalent: a Python rlimit would cap the podman/docker client,
not the containerized program, and `--tmpfs /tmp:size=64m` only bounds `/tmp` — the actual
working directory (`/work`) is an uncapped bind mount. `Limits.workdir_bytes` is a
best-effort mitigation, not a fix: after each run, `LocalExecutor.execute` sums the work
directory's total size and reports the run as `disk_exceeded` rather than `ok` when it is
over the cap. That stops a flood from being misreported as a successful run, but it does
**not** stop the bytes from landing on host disk in the first place — a write fast enough
to finish within the run's own time budget can still land more data on host disk than the
cap before this check ever runs. `local`/`local-bwrap`'s `RLIMIT_FSIZE` remains the harder
guarantee. A true byte cap for the container backend would need either a size-capped
tmpfs seeded through a different file-injection mechanism than today's one-shot `podman
run` with a pre-populated bind mount, or `--storage-opt` quotas, which are not portably
available across storage drivers — both are redesigns, not fixes, and out of scope here.

**Contract, and where it differs from AnimoRank.** The compile and run lines are
AnimoRank's verbatim (`gcc -Werror -Wall -o program main.c -lm -lpthread`, then
`./program`), and so is the public/all split between Run and Submit. Four things differ,
and the first is load-bearing:

- **Trailing whitespace is normalised before comparison.** AnimoRank compares stdout
  strictly. Every problem in `cases/problems/` stores its expected output without a
  trailing newline, so a strict comparison rejects a correct program that ends with
  `printf("%d\n", ...)` — on all nine.
- Compiled once and run N times, rather than once per case.
- 5s per run rather than 30, with the memory cap applied to the run and never to gcc —
  `--memory`/`--pids-limit` for the container backend, `RLIMIT_AS` for the local ones,
  neither ever passed to the compile step.
- `FunctionOutputTestCase` is not ported. `crowley_path` gets its `solvePath()` harness
  through `starter_code` instead.

## Sandbox mode

**Enter sandbox** in the header swaps the editors onto a scratch copy held in the browser.
Everything works the same — same tabs, same forms — but **nothing is written to disk**, so you
can gut the rubric, rewrite a prompt, and judge against the result without dirtying the repo.
`git status` stays clean. Leaving sandbox puts you back on the real files with your scratch copy
still saved for next time; **Reset sandbox** re-seeds it from disk, and **Promote to files**
writes it back through the same validation a normal save uses.

Sandbox adds a **Session** tab, where you are the student rather than the author:

- Start at Problem and work forward. Every criterion must PASS to unlock the next phase — a
  failed submission increments the attempt counter that feeds `{{ attempt }}` in the templates.
- **Skip ahead** unlocks a later phase without satisfying the earlier ones, for when you only
  want to poke at Design.
- **Carry earlier phases into the prompt** shows the judge what you wrote in previous phases.
  Off by default: with it off the prompt is byte-identical to what the Run tab sends.
- Each phase keeps a transcript of what was submitted and how it scored.

Because the Session judges the *sandbox* copy, an edit you make in the Criteria tab is in play on
the very next submission — which is the point: you can watch a rubric change land on a real
answer instead of guessing at it.

## The four phases

The first four steps of PCDIT. The first three are judged by a model reading prose; the
fourth is gated by a compiler, and the model only reviews code that already works. Test
stays with AnimoRank's autograder.

| Phase | id | The student submits |
|---|---|---|
| **Problem** | `problem_definition` | A restatement of the task, its inputs, and its outputs |
| **Cases** | `case_design` | Test cases worked by hand, including edge cases, with the tracing shown |
| **Design** | `algorithm_design` | An ordered plan in plain language, the state it carries, and how the output is produced |
| **Implement** | `implement` | A C program, checked against the problem's test cases |

A phase is a single YAML file. `artifact_fields` declares what the student submits; the
template's STUDENT ARTIFACT block loops over it, so adding a field in the Studio reaches the
prompt without a template edit. `task_description` is the student-facing instructions shown at
the top of a Session — it is read by people, never sent to the model.

## Layout

```
criteria/<phase>.yaml         the rubric: one PASS/FAIL rule per criterion
prompts/phases/<phase>.yaml   model settings, artifact fields, system prompt, user template
prompts/base/                 the shared output schema, plus hint.yaml, nudge.yaml and personas.yaml
cases/problems/<slug>.yaml    problem statements and public test cases
cases/suites/<phase>.yaml     regression fixtures pinning expected verdicts
notebooks/                    the walkthrough
src/clive/                    prompts.py (load/render/save), judge.py / hint.py / nudge.py (the calls)
src/clive/persona.py          a simulated student writing one phase; simulate.py runs the session
src/clive/studio/             server.py (routes + Studio), student.py (the student-facing API)
src/clive/providers/          one file per model vendor; CLIVE_PROVIDER picks which the judge uses
src/clive/executors/          container.py, local.py (two backends) and a registry; CLIVE_EXECUTOR picks which
src/clive/grade.py            one submission against a problem's test cases
src/clive/studio/static/editor.js   the Monaco module, shared by both pages
```

## Conventions

- **Bump `version` in `criteria/<phase>.yaml` when a rule's meaning changes.** The suites in
  `cases/suites/` pin `criteria_version`, so a fixture recorded against the old rubric is not
  silently re-read against the new one.
- **Record why a prompt changed in `prompts/CHANGELOG.md`**, not just what changed.
- **No `temperature`.** Sampling parameters were removed on current models and return HTTP 400.
  Depth is bought with `effort` plus adaptive thinking instead.
- **Thinking tokens come out of `max_output_tokens`.** A budget that looks generous for a
  verdict list can still truncate it.
- **Keep explanatory comments at the top of a YAML file.** Only the leading comment block
  survives a save from the Studio; a note sitting next to the key it describes is deleted on the
  next round-trip.
