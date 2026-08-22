# Changelog

> Please update this file whenever prompts are changed by documenting why each version changed.

## Sandbox support: problem_definition v3 -> v4, case_design and algorithm_design v1 -> v2 - 2026-08-20

**`task_description` added to every phase.** The phases described what the *judge* should do
but never what the *student* should do, which was fine while judging was the only thing the
repo did. A Sandbox session puts a person in front of the artifact form, so each phase now
carries the instructions that person reads. It is student-facing copy and is never sent to the
model — it appears in the Studio, not in the prompt.

**An optional EARLIER PHASES block, driven by `prior_artifacts`.** PCDIT phases are not
independent: the cases a student designs only make sense against the inputs they claimed in
Problem, and whether a Design step is a gap depends on what they already committed to reading.
The block is guarded by `{% if prior_artifacts %}`, so **a caller that passes nothing renders
byte-identically to the previous version** — verified by rendering the template against itself
with the block stripped. The notebook, which passes no such variable, is unaffected.

**One system-prompt rule covers the hazard the block introduces.** Prior-phase text is the
student's *own writing*, so unlike the problem statement it looks exactly like quotable
evidence. Without an explicit rule a judge can satisfy a criterion from work the student did in
an earlier phase and quote it as though it appeared in the current artifact — which would also
defeat the deterministic evidence audit, since that checks the current artifact only. The rule
states that earlier work is context, that it must never be quoted, and that a criterion fails if
only the earlier work satisfies it.

**problem_definition also had damage repaired.** Its `changelog` had been emptied and its
`artifact_fields` reordered to `inputs, outputs, summary` by a Studio save. The v3 and v2
rationale is restored and the order is back to `summary, inputs, outputs`, which is the order a
student fills the form in. `save_phase` now refuses to overwrite a non-empty changelog with an
empty one, so the same accident cannot repeat; clearing it deliberately is a file edit.

**Inline comments moved into the top-of-file header** in `problem_definition.yaml`. Only the
leading comment block survives a round-trip through the Studio (`read_header` in `prompts.py`),
so notes sitting next to the keys they described were being silently deleted on save.

## Three phases: problem_definition v2 -> v3, case_design v1, algorithm_design v1 - 2026-08-20

**Three phases now exist.** `case_design` (the "C" of PCDIT) and `algorithm_design` (the "D")
join `problem_definition`. Implement and Test are left to AnimoRank's autograder, so the
judged phases are exactly the ones whose artifact is prose.

Each new phase inherits the v2 judging contract and adds one instruction of its own, because
each has a distinct failure mode:

- `case_design` tells the judge to **compute every case itself before ruling on correctness**,
  and that a case copied from the public test cases is not a case the student designed. A
  plausible-looking but wrong expected output is exactly what this phase exists to catch, and
  a judge that reads rather than computes will wave it through.
- `algorithm_design` tells the judge that **inefficiency is not a failure** and to read the
  steps in order, checking each one can actually be executed. Without the first, judges mark
  down clumsy-but-correct plans against criteria that say nothing about efficiency.

**`artifact_fields` added to every phase.** A phase now declares what the student submits
(id, label, hint, box size). The STUDENT ARTIFACT block loops over that declaration instead of
naming `summary`/`inputs`/`outputs` literally, so the three phases share one template shape and
a field added in CLive Studio reaches the prompt without a template edit. The rendered output
for `problem_definition` is unchanged.

**`model.id` added.** The model was previously hardcoded in the notebook, which meant every
phase had to use the same one and changing it was a code edit. It defaults to `claude-opus-5`.

**`label` and `order` added** so the Studio can present the phases as a sequence.

**Criteria moved out of the notebook into `criteria/<phase>.yaml`.** They were a Python literal
in `notebooks/00_overview.ipynb`, which made them uneditable by anyone not running the notebook
and impossible to version independently of it. The file carries its own `version`, which is what
`cases/suites/*.yaml` already pinned as `criteria_version`.

**Guidance is now indented under its criterion** in the CRITERIA TO JUDGE block
(`{{ c.guidance | trim | indent(2) }}`). Guidance moved from single-line Python strings to
multi-line YAML blocks, and without the filter every continuation line rendered flush against
the left margin, visually detaching it from the criterion it belongs to.

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
