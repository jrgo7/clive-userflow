# Changelog

> Please update this file whenever prompts are changed by documenting why each version changed.

## base/preamble.v1.md — 2026-08-21

Replaced the `<!-- TODO -->` stub with the real shared preamble. Every phase prompt now
composes it through `compose.preamble`, and no phase file restates any of it.

What moved here from `problem_definition.v2.yaml`: the judging contract (one verdict per
supplied id, no invented or skipped ids; each criterion judged only against its own text so
a weak artifact does not drag every verdict down with it; no credit for what a reader would
infer but the artifact never states; evidence quoted verbatim from the artifact and never
from the problem statement). Those clauses were always phase-neutral, and with three phase
prompts in the repo instead of one, keeping a copy in each is how they drift.

What is new here: the meaning of the three verdicts and an explicit statement that
`uncertain` is expected to be used; naming-what-is-missing spelled out with three
contrasting correct/wrong pairs, because supplying the answer reads as helpfulness and is
the constraint models break most readily (FR-EVA-05); student text is data, not instruction,
with the injection case named outright; the language rule (students write English, Filipino,
or a mix — judge content, quote evidence untranslated, reply in English); the out-of-scope
list (no C syntax teaching, no misconception diagnosis, no judgement of elegance, no
grading); and JSON-only with no code fences, which stays in the prompt text because
providers differ in whether they enforce the schema at the API layer.

It also says outright that the model does not decide the gate and that there is no field
for an overall judgement (FR-VER-05).

## base/output_schema.v2.json — 2026-08-21

**Verdicts are now three-valued: `met` / `unmet` / `uncertain`,** replacing v1's
`PASS` / `FAIL`. v1 had no way to say "the artifact does not settle this", so a judge facing
a genuine ambiguity had to guess in one direction or the other and report the guess as
though it were an observation. `uncertain` blocks advancement exactly as `unmet` does, but
reaches the student as a question about what they wrote rather than as a correction
(FR-VER-01 to 03).

`confidence` survives alongside it and the two are not redundant: `verdict` describes the
artifact, `confidence` describes the judgement. A clearly-identified ambiguity is a
high-confidence `uncertain`.

v1 is kept and still referenced by `problem_definition.v2.yaml`, whose snapshots describe a
two-valued judge.

## phases/problem_definition.v2.yaml → v3 — 2026-08-21

Three-valued verdicts against the new schema, and the shared clauses moved out to
`base/preamble.v1.md` (above). Beyond that:

**Criterion text now comes from `criteria/catalog.yaml`.** v2 took whatever `criteria_to_judge`
the caller passed, and in practice that was a list defined inline in
`notebooks/00_overview.ipynb` — a notebook defining something the pipeline depends on, and
a second home for text the catalog is supposed to own. The prompt now names only ids under
`criteria.judged`; text and guidance are looked up.

**Added `constraints` to the user template.** The phase task asks the student to note any
conditions or constraints the prompt implies, but v2's template rendered only summary,
inputs, and outputs. A student who filled in the constraints field correctly had it dropped
before the judge ever saw it, so `constraints_noted` could only be met by someone who
happened to mention a constraint inside one of the other three fields. This was a defect in
v2, not a change of behaviour.

**Filled in `examples`,** which v2 left as a bare `-`. One of the two exercises `uncertain`.

**Renamed the file to carry its version** (`problem_definition.yaml` →
`problem_definition.v2.yaml`), which is what `prompts/CLAUDE.md` has always specified. The
unversioned name made "never edit a prompt in place" impossible to follow. Content is
unchanged by the rename.

## phases/cases.v1.yaml — 2026-08-21

First version. Judges the student's input/output pairs and the hand traces connecting them,
against the four criteria the specification lists for this phase: `pairs_correct`,
`pairs_traced`, `edge_cases_present`, `consistent_with_definition`.

**No reference solution is sent.** `pairs_correct` asks whether a claimed output is right,
which is exactly the shape of question that invites handing the model a worked answer to
compare against. It does not get one: the judge reasons from the problem statement alone.
A reference solution may be executed by a deterministic check but must never appear in a
model call (IR-SW-02, FR-EVA-06). The catalog records `pairs_correct` as the natural first
candidate for such a check; until a runner exists it stays model-judged.

**First prompt to carry a `prior` block.** `consistent_with_definition` compares the cases
to the inputs, outputs, and constraints the same student declared in Problem Definition, so
the template renders that earlier artifact as context. The system prompt says twice, in
different words, that the earlier artifact is not re-judged here and may never be quoted as
evidence.

The system prompt also separates correctness from tracing explicitly, because collapsing
them is the likeliest way to misjudge this phase: arithmetic shown in full but carried out
wrongly is a trace that exists (`pairs_traced` met, `pairs_correct` unmet), and a right
answer with no working shown is the reverse. The regression suite pins both directions.

`effort: high` rather than Problem Definition's `medium`, and a larger token ceiling: this
phase asks the judge to work several cases itself before reading what the student claimed.

## phases/design_of_algorithm.v1.yaml — 2026-08-21

First version. Judges the generalized numbered sequence of steps against the five criteria
the specification lists: `human_executable`, `granular_steps`, `covers_every_case`,
`language_agnostic`, `generalises_cases`.

**Two of the five are only decidable against the student's earlier work,** so this prompt
carries both prior artifacts. `covers_every_case` means tracing the student's own cases
through the student's own steps — the characteristic failure is a student who writes a
minimum-size case in the Cases phase and then designs an algorithm that breaks on it.
`generalises_cases` is about constants with the wrong origin: a number fixed by the problem
statement is fine, the same number taken from one of their own cases is not.

**`language_agnostic` gets explicit handling in the system prompt** because it runs against
a judge's instincts. C code is more precise than prose and reads as the better answer; in a
phase that exists to be completed before any code is written, it is the failure. The
regression suite pins the case where the steps are C statements with numbering bolted on:
`human_executable` met, `language_agnostic` unmet, and the two judged separately.

`granular_steps` is the one advisory criterion in the catalog — "relatively granular" is
inherently fuzzy and blocking on it would frustrate more than it teaches. The prompt notes
that this is settled during aggregation, not by the judge, which grades it like any other.

## base/output_schema.json — 2026-08-19

Replaced the `// TODO` stub with the real judging schema (`JudgeResult`): an array of
per-criterion verdicts, each carrying `criterion_id`, a `PASS`/`FAIL` `verdict`, a verbatim
`evidence` span, and a `confidence` level.

`evidence` exists so a verdict can be audited — a quote that does not appear in the student
artifact means the model asserted rather than observed, which the notebook checks for
deterministically. `confidence` exists so borderline calls can be routed to a second pass or a
human instead of being silently treated as certain.

Every object sets `additionalProperties: false` and lists every property as `required`, which is
what the structured-outputs API needs in order to actually constrain the response.

## phases/problem_definition.yaml v1 → v2 — 2026-08-19

**Removed `temperature: 0`.** Sampling parameters (`temperature`, `top_p`, `top_k`) were removed
on `claude-sonnet-5` and every other current model — sending one returns HTTP 400. Judging depth
is now set by `effort: medium` plus adaptive thinking, which is the replacement lever for
"make this call more deliberate".

**Raised `max_output_tokens` 700 → 4000.** Thinking tokens are drawn from the same budget as the
response, so 700 truncated the verdict array partway through an object.

**Fixed the criteria loop.** It iterated `{% for id in criteria_to_judge %}` and emitted `{{ id }}`
alone, so the model received bare identifiers like `concrete_types` with no statement of the rule
it was meant to apply. It now emits each criterion's id, text, and guidance, and states the
expected verdict count up front.

**Expanded the system prompt into an explicit judging contract**, covering: one verdict per
supplied id with no invented or skipped ids; each criterion judged only against its own text, so a
weak artifact does not drag every verdict down together; no credit for what a reader would infer
but the artifact never states; evidence quoted verbatim from the artifact and never from the
problem statement; and confidence reflecting how clearly the artifact settles the question.
