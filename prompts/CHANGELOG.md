# Changelog

> Please update this file whenever prompts are changed by documenting why each version changed.

## base/personas.yaml v5 - nods_along cannot write either - 2026-09-02

**`nods_along` is now inarticulate as well as lost.** Getting a thought into words is hard
for it on its own, separately from having the thought: answers come out as fragments, a
phrase with the important half missing, or the same small idea said twice. It never
elaborates, never reaches for an example, and where a box asks it to explain its reasoning
it restates what it did instead.

**This is not a length knob.** `minimalist` already writes little, on purpose, to be done.
This one writes little because it has run out of words and would write more if it could,
and the behaviour says so explicitly so the two do not collapse into each other.

**What it buys the rubric.** A criterion this persona fails may be catching a student who
did not understand, or one who understood and could not say it -- two failures the rubric
currently scores identically. `novel_wording`, `work_is_shown`, `case_purpose_stated` and
`state_is_named` all ask the student to *articulate* something, and this is the only
character that isolates that. A failure there is worth reading before it is trusted.

## base/personas.yaml v4 - the one who nods along - 2026-09-02

**A first-timer who never asks.** `nods_along`: the only prior experience is copying HTML
tags that worked when typed correctly, so programming reads as shapes to reproduce
accurately. The lecture moves too fast and demonstrates code without explaining why it
works, so there is a store of syntax and no sense of what it is for. Anything arithmetic
closes them down -- a division, a percentage, "two decimal places" -- and they go vague
on it or write more about a safer part of the box. Instructions are read absolutely
literally, and anything implied rather than stated is missed entirely.

**`help_seeking: never` is the character, not a default.** Being embarrassed to ask an
obvious question is the defining trait, so the confusion compounds instead of being
cleared: gaps are covered with a confident-sounding sentence that says nothing, never with
"not sure", and later phases rest on earlier answers that were never understood.

**That makes it the controlled counterpart to `utter_beginner`** -- comparable competence,
opposite help behaviour, nothing else different. Run both on one problem and the gap
between them is what the hint is actually worth, which no single persona can tell you.

**It is also the sharpest test of the v3 finding.** A character that follows the letter of
every instruction and almost none of its intent should pass exactly those criteria that
were only ever checking wording. Whatever it passes is worth re-reading.

## base/personas.yaml v3 - instructions are not a checklist - 2026-09-02

See the v3 entry inside `prompts/base/personas.yaml`: the phase `task_description` spells
out 11 of the 12 gating criteria as instructions, so a model that simply follows it
satisfies the rubric whatever character it was told to play. The system prompt now says so.

## base/personas.yaml v2 - the beginner, and the help button - 2026-09-02

**A persona can now press the help button.** New per-persona field `help_seeking`:
`never` (the default, and every persona's behaviour before this existed), `when_stuck`
(asks after a failed attempt) or `eager` (asks before writing anything). The loop calls
the real `hint()` and renders what comes back into a HELP block. Until now the hint was
the one call a simulation never exercised.

**Only the hint's prose is handed to the character; the criterion it points at is not.**
A student sees that label on screen, but a persona that could read the rule would satisfy
it, and the run would then report the hint as more use than it actually is.

**New persona `utter_beginner`.** A student who has not yet learned how to do any of this:
drifts between describing, testing and planning because the difference is not yet clear;
writes unevenly, some boxes with real effort about the wrong thing and others with a
fragment or "not sure"; contradicts itself between boxes; misreads one clause of an
instruction and misses the rest; takes help very literally and applies it to the wrong
box. It asks for help before writing a word, which is the empty-form case the hint was
built for.

This is the hardest case for the whole system and the most realistic failure in an
introductory course. The criteria have to fail work that is thin and inconsistent without
any single one of them being the thing that explains why, and the nudge has to give
somewhere to start to someone who does not yet know what the phase is asking for. The
question a run answers is whether it converges at all or just repeats itself.

## base/personas.yaml v1 - simulated students - 2026-09-02

**A rubric can now be walked end to end without waiting for a class.** New file
`prompts/base/personas.yaml` holds the frame, the output contract and six characters;
`src/clive/persona.py` makes the call and `src/clive/simulate.py` runs the loop -- write,
judge, nudge, revise, advance. The judge, the nudge and the gating are the real ones
against the saved criteria. Only the student is synthetic.

**The persona is never shown the criteria,** and `render_persona_prompt` takes no rubric
argument, so no caller can pass one. A simulated student handed the rubric writes to the
rubric, and the run then measures the rubric against itself. It *is* shown the verdicts and
the nudge from its previous attempt, because that is what a real student has on screen --
which is what makes a run a test of whether the nudge actually helps. `tests/test_simulate.py`
asserts both halves against every criterion in the repo.

**Six characters, each built to trip something specific.** `minimalist` (substance rather
than presence), `copier` (own words), `code_first` (plain language, and not solving during
Problem), `confident_wrong` (shown working, correct expected outputs), `feedback_deaf`
(whether the nudge escalates or repeats), and `diligent` as the control -- if that one
cannot pass, the rubric is too harsh and nothing the others tell you is worth reading yet.
`blurb` records what each is for, because a persona whose purpose is not written down
becomes a persona nobody trusts the result of.

**Character sits in the user turn, not the system prompt,** matching the judge, hint and
nudge documents: static system, templated user. The output schema is built per phase from
`artifact_fields`, so a phase that gains a box in the Studio gains a key here with no code
change.

**A phase that is never passed stops the run.** That is the gating rule rather than a
shortcut -- a student who cannot get through Problem never sees Cases, and a simulation
that marched on regardless would be reporting on a system nobody uses.

## base/nudge.yaml v1 - the nudge call - 2026-09-02

**A student who fails a phase is told what is holding them, and given one thing to fix.**
New file `prompts/base/nudge.yaml` holds the system prompt and template;
`src/clive/nudge.py` makes the call, mirroring `hint.py` and `judge.py`. It is pushed
after a failing submit rather than asked for -- a student who has just been told they did
not pass should not have to go looking for where to start.

**The nudge may only ever name a gating criterion the student actually failed,** which is
the mirror of the hint's rule and not a reversal of it. The two calls fire at different
moments. A hint runs with no verdicts in hand, so naming a gate there would tell a student
what they are failing before anything judged them; a nudge runs on verdicts already on
screen, where naming one back reveals nothing they were not just shown, and refusing to
would leave them guessing. Enforced in code the same way: `failing_gates` selects the set
inside `nudge()` so no caller can widen it, and a reply naming anything outside it -- an
advisory criterion, a criterion that passed, an invented id -- is refused rather than shown.
`failing_gates` is the exact complement of `advisory_criteria`, so no criterion falls
through both and an unmarked one is treated as gating.

**Acknowledge all, nudge one.** The summary must account for every failing gate: a student
who fixes one thing, resubmits, and finds three more waiting learns the system was holding
something back. But `reason` and `nudge` concern one criterion only, because four
corrections at once produce four shallow edits. The set is computed in code and returned as
`failing` for the caller to render, so acknowledgement is structural -- a summary that
forgets a criterion cannot hide it. The model is asked to pick the most upstream failure,
falling back to rubric order, which is the order the phase's criteria were written to be
read in.

**A criterion the judge returned no verdict for is not nudged at.** The Studio treats a
missing verdict as blocking, and rightly -- it is not a pass -- but it is a broken judge
contract rather than something the student wrote wrong, so there is no failure to describe.
It stays reported as `missing_ids`.

**It pins no `model.id`,** for the reason `base/hint.yaml` gives, and carries the same
`history` seam guarded by `{% if history %}`. The evidence line uses one expression rather
than an `{% if %}` block because the environment sets `trim_blocks`, which would eat the
newline after `{% endif %}` and run each criterion into the next.

## base/hint.yaml v1 - the hint call - 2026-09-01

**A stuck student can ask for one hint.** It names a single criterion to improve, and
comes with one sentence saying why the student appears stuck. New file
`prompts/base/hint.yaml` holds the system prompt and template; `src/clive/hint.py`
makes the call, mirroring `judge.py`.

**The hint may only ever point at an advisory criterion,** and the model is not shown
the gating ones at all. Pointing a stuck student at the requirement they are failing
hands them the answer, which is the one thing this system exists not to do; naming
optional depth instead gives them somewhere to think from, and the work of getting
there is usually what surfaces the blocking gap themselves. This is enforced in code,
not just asked for in the prompt: `advisory_criteria` selects the offered set inside
`hint()` so no caller can widen it, and a reply naming anything outside that set is
refused rather than shown.

**One shared document, not one per phase.** The hint logic is phase-independent -- it
reads whichever phase's advisory criteria it is handed -- so writing it out three times
would only let three copies drift. It does not compose `base/preamble.v1.md`, which is
written for judging (three verdicts, one per criterion, evidence spans) and would
contradict this job; the doctrine the two share is "name what is missing, never supply
it", and an edit to one wants the same edit in the other.

**It pins no `model.id`.** Every phase pins its own, but a shared document naming an
Anthropic model would be wrong at a repo running on DeepSeek, so the call falls back to
whichever provider `CLIVE_PROVIDER` selects and that provider's default.

**No judge run is required first.** The hint reads the artifact, never the verdicts,
which is what lets a student ask for one while still staring at an empty form. It is
offered on demand from an "I'm stuck" button rather than pushed after a failed submit.

**The conversation seam is `history`.** Diagnosis should eventually be a dialogue. The
parameter is threaded through `hint()` and rendered by a `{% if history %}` block, so
passing a transcript works today and passing nothing renders exactly the single-shot
prompt. True multi-turn also needs the provider seam to take a message list instead of
one `user` string, which it does not yet.

## Gating and advisory criteria: all three rubrics v1 -> v2 - 2026-09-01

**Criteria now declare what a failure costs.** `criteria/<phase>.yaml` gains a `gate` field
per criterion, using the vocabulary `criteria/catalog.yaml` already defined for it:
`gating` is the bare minimum the phase demands, and a FAIL holds the student there for
another attempt; `advisory` is judged and reported exactly like any other criterion but
never blocks advancement. Every criterion that existed before this change is `gating` —
they were all written as requirements — and an omitted `gate` is read as `gating`, so the
safe way to be wrong is to hold a student one attempt too long rather than advance them
past a phase they never satisfied.

**Three advisory criteria added per phase**, covering the understanding each phase is
trying to build rather than the floor it enforces: input ordering, exact output form, and
named ambiguity in Problem; case distinctness, stated case purpose, and out-of-range input
in Cases; explicit initialisation, coverage of the student's own edge cases, and loop
termination in Design. Each one's guidance says what an honest PASS looks like when the
problem statement offers nothing to find — a student must not be marked down for declining
to invent an ambiguity, a format, or a loop that is not there.

**The Sandbox advancement rule now reads the gate.** It previously required every verdict
to be PASS, which would have made a new advisory criterion block exactly like a gating one
— the opposite of what the field means. Only gating failures cost an attempt now. A
*missing* verdict still blocks whatever the gate: a judge that skips a criterion has broken
its contract, which is not the same as an advisory FAIL.

**`gate` is not sent to the judge.** The judge rules on one criterion at a time against its
own text and guidance; telling it that a rule is optional invites leniency on that rule.
Which failures block is an advancement decision, made from the verdicts afterwards.

**`save_criteria` preserves and validates it.** It rebuilds each criterion from a fixed set
of keys, so a `gate` written by hand would have been silently dropped by the next Studio
save — the same accident that once emptied the problem_definition changelog. An unknown
value is refused rather than coerced.

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
