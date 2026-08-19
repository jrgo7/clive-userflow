# Changelog

> Please update this file whenever prompts are changed by documenting why each version changed.

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
