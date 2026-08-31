# CLive User Flow

This repository outlines and demonstrates the various steps in CLive's user flow.
CLive aims to adopt the PCDIT framework for solving programming problems as an extension
module for AnimoRank (an open-source programming practice platform).

There are two ways in: a set of Jupyter notebooks that walk through the mechanics of a
judging call, and **CLive Studio**, a local app for authoring the things those calls run on.

## CLive Studio

```bash
uv sync
cp .env.example .env      # then paste your ANTHROPIC_API_KEY
uv run clive-studio       # opens http://127.0.0.1:8765
```

`--port N` to move it, `--no-browser` to stop it opening a window. Editing works without
an API key; only the Run tab needs one.

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

The phase strip at the top switches between the three phases. Run reports each verdict with
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

## The three phases

The first three steps of PCDIT, the ones where a judge reads prose rather than code.
Implement and Test stay with AnimoRank's autograder.

| Phase | id | The student submits |
|---|---|---|
| **Problem** | `problem_definition` | A restatement of the task, its inputs, and its outputs |
| **Cases** | `case_design` | Test cases worked by hand, including edge cases, with the tracing shown |
| **Design** | `algorithm_design` | An ordered plan in plain language, the state it carries, and how the output is produced |

A phase is a single YAML file. `artifact_fields` declares what the student submits; the
template's STUDENT ARTIFACT block loops over it, so adding a field in the Studio reaches the
prompt without a template edit. `task_description` is the student-facing instructions shown at
the top of a Session — it is read by people, never sent to the model.

## Layout

```
criteria/<phase>.yaml         the rubric: one PASS/FAIL rule per criterion
prompts/phases/<phase>.yaml   model settings, artifact fields, system prompt, user template
prompts/base/                 the shared output schema the judge is constrained to
cases/problems/<slug>.yaml    problem statements and public test cases
cases/suites/<phase>.yaml     regression fixtures pinning expected verdicts
notebooks/                    the walkthrough
src/clive/                    prompts.py (load/render/save), judge.py (the call), studio/ (the app)
src/clive/providers/          one file per model vendor; CLIVE_PROVIDER picks which the judge uses
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
