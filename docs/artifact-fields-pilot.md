# Artifact-fields pilot

Finalize an **initial** `artifact_fields` set for each of the three prose phases
(`problem_definition`, `case_design`, `algorithm_design`) by piloting candidate
layouts interactively in CLive Studio's sandbox against a small set of
hand-labelled student artifacts.

The judgement here is yours: your PASS/FAIL label on each pilot artifact is the
ground truth, and the pilot measures how well each field layout lets the judge
reproduce it.

## Scope

**In scope:** the `artifact_fields` list in each phase YAML — which boxes exist,
their `id` / `label` / `hint` / `rows`, and their order.

**Not in scope:** criteria text or guidance, the system prompt / judging
contract, new problems, and any systematic agreement-scoring script or wired-up
`cases/suites/` runner. If the pilot surfaces a criteria problem, write it down
and keep going — do not fix it in this pass.

**Output:** one chosen layout per phase, written to the phase YAMLs with a
`version` bump and a changelog entry, plus the pilot artifacts and your labels
saved for reuse.

## Prerequisites

- [ ] `uv sync` is clean and `uv run clive-studio` opens the app.
- [ ] API keys for **both** providers are in `.env`. The phases do not share a
      model: `problem_definition` and `case_design` pin `model.id: deepseek-chat`
      (needs `DEEPSEEK_API_KEY`), `algorithm_design` pins `claude-opus-5` (needs
      `ANTHROPIC_API_KEY`). Either set both, or temporarily point all three
      `model.id` at one model so the pilot is consistent — just don't promote
      that change.
- [ ] You know how to: switch phases on the phase strip, pick a problem, **Enter
      sandbox**, edit the Prompt tab, run a judge in the Run tab, and **Promote
      to files**.

All piloting happens **in sandbox** so candidate layouts never touch disk.
`git status` stays clean until you promote a winner.

---

## Step 0 — Assemble labelled pilot artifacts

For each phase, put ~5–7 student artifacts in a scratch file (plain text or YAML
you paste from — it does not need to be a valid suite file). For each artifact,
write your own PASS/FAIL for every criterion in that phase.

A draft set is in [`artifact-fields-pilot-corpus.yaml`](artifact-fields-pilot-corpus.yaml):
6 artifacts for `problem_definition`, 6 for `case_design`, 7 for `algorithm_design`,
each with proposed labels and per-candidate field-mapping notes. **Review every
label before Step 3** — the labels there are a starting point, not the standard.

Target spread per phase:

| Artifact        | Purpose                                                   |
| --------------- | --------------------------------------------------------- |
| 1 clean pass    | every criterion PASS                                      |
| 1 per criterion | that criterion FAILs, the rest ideally PASS — isolates it |
| 1 borderline    | genuinely ambiguous; you expect the judge to wobble       |

Recyclable material (the prose is reusable; the old `expect:` blocks are **not** —
they reference criteria that no longer exist for two of the three phases):

- **`problem_definition`** — `cases/suites/problem_definition.yaml` already has
  `good_artifact` (clean), `copied_artifact` (`novel_wording` + `concrete_types`
  fail), `sparse_artifact` (`constraints_noted` + `concrete_types` fail),
  `borderline_paraphrase` (borderline `novel_wording`). Add one that isolates
  `constraints_noted` (types fine, constraints simply absent).
- **`case_design`** — `cases/suites/cases.yaml`: `good_cases`, `untraced_cases`
  (`work_is_shown` fail), `wrong_output_case` (`outputs_are_correct` fail),
  `interior_only_cases` (`has_edge_case` fail), `underspecified_rounding`
  (borderline). Add one where cases are described only in the abstract
  (`has_normal_case` fail).
- **`algorithm_design`** — `cases/suites/design_of_algorithm.yaml`:
  `good_algorithm`, `c_code_algorithm` (`not_c_code` fail), `coarse_algorithm`
  (`ordered_steps` fail), `misses_minimum_case` (`inputs_are_consumed` fail),
  `hardcoded_algorithm`, `ambiguous_step` (borderline). Add one that never names
  its accumulator/counter (`state_is_named` fail).

All pilot artifacts target `problem.grade_average` (the only problem defined).

- [x] `problem_definition` — artifacts assembled and labelled
- [x] `case_design` — artifacts assembled and labelled
- [x] `algorithm_design` — artifacts assembled and labelled

---

## Step 1 — Candidate layouts

Starting candidates below. Each row shows the fields and which criterion reads
which box. Adjust or add your own; keep variants small (a split, a merge, a
rename), not full redesigns.

### `problem_definition` — criteria: `novel_wording`, `concrete_types`, `constraints_noted`

| ID               | Fields                                        | Mapping / question it answers                                                                                                                                                                           |
| ---------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P1** (current) | `summary`, `inputs`, `outputs`                | `novel_wording`→summary; `concrete_types`→inputs+outputs; `constraints_noted`→inputs (the hint asks "what the statement guarantees about it"). Does constraints coverage survive with no dedicated box? |
| **P2**           | `summary`, `inputs`, `outputs`, `constraints` | `constraints_noted`→constraints. Reword the `inputs` hint to type+count only so students don't split-brain. Matches the `constraints:` key the old suite fixtures already carry.                        |
| **P3**           | `summary`, `inputs`, `constraints`, `outputs` | Same as P2 with `constraints` next to `inputs`, since constraints are usually about inputs. Does adjacency change what students write?                                                                  |

### `case_design` — criteria: `has_normal_case`, `has_edge_case`, `work_is_shown`, `outputs_are_correct`

| ID               | Fields                                              | Mapping / question it answers                                                                                                                                                              |
| ---------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **C1** (current) | `normal_cases`, `edge_cases`, `reasoning`           | Each case box holds input + output + trace; `work_is_shown` and `outputs_are_correct` read both case boxes. Is `reasoning` load-bearing, or only scaffolding half-read by `has_edge_case`? |
| **C2**           | `normal_cases`, `edge_cases`, `traces`, `reasoning` | `work_is_shown`→`traces` (dedicated). Risk: separating the trace from its case makes `outputs_are_correct` cross-reference, and students may leave `traces` empty.                         |
| **C3**           | `cases`, `reasoning`                                | One case box; the student labels which case is the boundary in-line or in `reasoning`. Fewer boxes. Does `has_edge_case` ("identified as such") survive the merge?                         |

### `algorithm_design` — criteria: `ordered_steps`, `not_c_code`, `inputs_are_consumed`, `state_is_named`, `output_is_produced`

| ID               | Fields                                         | Mapping / question it answers                                                                                                                                                         |
| ---------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **D1** (current) | `steps`, `state`, `output_step`                | `state_is_named`→`state`; `output_is_produced`→`output_step`; the rest→`steps`. Do students duplicate the output in `steps` and leave `output_step` redundant, or thin out `state`?   |
| **D2**           | `inputs_read`, `steps`, `state`, `output_step` | `inputs_are_consumed`→`inputs_read` (dedicated). Four boxes — most burden. Risk: reading is part of the flow; pulling it out can make `steps` start mid-air and hurt `ordered_steps`. |
| **D3**           | `steps`, `state`                               | Output folded into the last step; `output_is_produced` reads the tail of `steps`. Tests whether a dedicated output box is load-bearing. Two boxes.                                    |

- [x] Candidate list finalised for all three phases

---

## Step 2 — Desk-check (no runs)

Open the **Criteria** tab beside the **Prompt** tab's field editor. For each
candidate, tick:

- [x] **Coverage** — every criterion has at least one box a student would
      naturally use for its evidence.
- [x] **No orphan criterion** — none whose only home is "all boxes at once".
      (`case_design` C3: `has_edge_case`'s "identified as such" leans on
      `reasoning` — a known risk to watch in Step 3, not a disqualifier.)
- [x] **No dead box** — every field is read by ≥1 criterion, or has an explicit
      scaffolding job you can name.
- [x] **No leakage** — no box that invites another phase's work (e.g. a
      "how you'll solve it" box in `case_design`).

Dropped in the desk-check: **P3** (same layout as P2, only reordered), **C2**
(adds a box and splits the evidence `outputs_are_correct` needs to re-derive a
case), **D2** (pulling reads out of `steps` can manufacture the very
"referenced but never introduced" gap that `inputs_are_consumed` and
`state_is_named` exist to catch).

Kill any candidate with an uncovered criterion or an unjustified dead box.
**Carry exactly two survivors per phase** — the current layout plus the best
alternative. Two is the minimum useful comparison; more than two multiplies the
run count in Step 3 without much added signal for an *initial* set.

| Phase                | Survivor A                                | Survivor B                                        | One-line reason B is worth testing |
| -------------------- | ----------------------------------------- | ------------------------------------------------- | ---------------------------------- |
| `problem_definition` | **P1** `summary, inputs, outputs`         | **P2** `summary, inputs, outputs, constraints`    | `constraints_noted` gets a dedicated box instead of riding on the `inputs` hint; `summary/inputs/outputs` keep their current order. If run, reword the `inputs` hint to type + count only. |
| `case_design`        | **C1** `normal_cases, edge_cases, reasoning` | **C3** `cases, reasoning`                      | Fewer boxes, all evidence for `outputs_are_correct` kept together — tests whether a dedicated edge box is load-bearing for `has_edge_case`. |
| `algorithm_design`   | **D1** `steps, state, output_step`        | **D3** `steps, state`                             | Output folds into the last step, which `output_is_produced` already assumes — tests whether `output_step` is load-bearing or ceremony. |

---

## Step 3 — Run the pilot

Do one phase fully before moving to the next.

1. [ ] `uv run clive-studio`. On the phase strip, select the phase. Select
       `grade_average` as the problem.
2. [ ] Header → **Enter sandbox**.
3. [ ] **Prompt tab** → set `artifact_fields` to **survivor A** (edit `id` /
       `label` / `hint` / `rows`, reorder as needed). Save (sandbox save — no
       disk write).
4. [ ] **Run tab** → for each pilot artifact:
   - Paste its text into the boxes, re-keyed to A's fields. A **merge** =
     concatenate the old fields into one box; a **split** = cut one old field
     into two. Do this faithfully by hand.
   - Set **Attempt** = 1, click **Run**.
   - Record, per criterion: judge verdict vs. your label (agree / disagree);
     whether the evidence quote came from the box you *intended* that criterion
     to read; any **"this quote does not appear in the artifact"** flag or
     missing / invented-id warning.
5. [ ] Re-run each **borderline** artifact 2 more times. Note if verdicts flip
       between runs — the judge is not deterministic (adaptive thinking +
       non-zero effort).
6. [ ] **Prompt tab** → switch `artifact_fields` to **survivor B**. Repeat 4–5
       with the same artifacts re-keyed to B's boxes.
7. [ ] Compare the two tables.

Results table (one row per artifact × criterion × layout):

```
phase | layout | artifact | criterion | my label | run1 | run2 | run3 | evidence box ok? | notes
```

- [ ] `problem_definition` — both survivors run, table filled
- [ ] `case_design` — both survivors run, table filled
- [ ] `algorithm_design` — both survivors run, table filled

---

## Step 4 — Decide

The decision is **per phase**, and it is driven by the *per-criterion* shape of
the results, not a single headline number. Two layouts can tie on total
agreement while one quietly breaks the criterion the phase exists to protect.

### 4a. Compute the numbers

The unit is one **assertion** = one (artifact × criterion) pair for a layout.
Per phase that is `problem_definition` 6×3 = **18**, `case_design` 6×4 = **24**,
`algorithm_design` 7×5 = **35** assertions per layout.

For each assertion take the **majority verdict** across your runs (run 1 for
ordinary artifacts; best-of-3 for borderline). Then, per layout:

- **Verdict agreement** — assertions where majority verdict == your label, ÷
  total. Report overall **and per criterion** (one row each) — the per-criterion
  breakdown is the signal; the overall number hides it.
- **Confusion matrix** — TP / TN / **FP** (judge PASS, your label FAIL — a bad
  artifact waved through) / **FN** (judge FAIL, your label PASS — a good student
  blocked). Track FP and FN *separately*: for a gate a false pass is worse, so a
  layout that swaps one FN for one FP has not improved.
- **Evidence localisation rate** — of assertions where the judge returned a
  quote, the fraction quoted from the box you intended for that criterion.
- **"Quote not found" count** and **missing / invented-id count** — should be
  near zero; more of them means the layout is structurally confusing the model.
- **Borderline stability** — of the borderline assertions (3 runs each), how
  many came out **2–1** rather than **3–0**. Fewer split calls = more
  predictable where your own label was already a judgement call.
- **Box count** — P1 3 / P2 4, C1 3 / C3 2, D1 3 / D3 2. Tie-breaker only.

Scorecard per phase:

| Metric | A | B | Better |
| --- | --- | --- | --- |
| Agreement, overall | /18 | /18 | higher |
| Agreement, per criterion (one row each) | | | higher |
| False passes (FP) | | | lower — weighted worse |
| False fails (FN) | | | lower |
| Evidence localisation rate | | | higher |
| "Quote not found" count | | | lower |
| Missing / invented-id count | | | lower |
| Borderline calls that were 2–1 | | | lower |
| Box count | | | fewer |

**How big a difference counts.** At n = 18–35 with one run for most assertions, a
1–2 assertion gap is noise. Treat a layout as better only if agreement differs by
**≥ ~3 assertions** (>~10%), **or** there is a clear per-criterion story (B wins
the criterion the phase protects, or a criterion moves from mostly-wrong to
mostly-right), **or** B is materially worse on localisation / "quote not found" /
id warnings. Within noise on everything → **keep the incumbent**; "no measured
difference, P1/C1/D1 retained" is a legitimate result for an *initial* set. Do
not collapse the scorecard to one composite — at this sample size the shape
matters more than a scalar, and a composite hides the FP/FN asymmetry.

### 4b. Triage every disagreement — do not just count it

For each cell where the majority verdict ≠ your label, read the evidence quote
and sort it:

- **Misrouted evidence** — the judge quoted the wrong box, or "quote not found".
  *Counts against the layout* — this is the layout doing its job badly.
- **Right box, wrong call** — the judge quoted the box you intended but reasoned
  to the wrong verdict. *Does not count against the layout* — it is a
  criterion-wording or model-capability issue. Note it for a later criteria pass.
- **Your label was off** — fix the label in the corpus and re-score both layouts.

Only the first kind should move the decision.

### 4c. Apply the tie-breakers, in order

1. **Per-criterion agreement**, after 4b. A layout that lifts one criterion and
   sinks another has not improved — look at *which* criteria moved. A regression
   on the criterion the phase is built around (`outputs_are_correct` for
   `case_design`, `not_c_code` / `state_is_named` for `algorithm_design`,
   `novel_wording` for `problem_definition`) is close to disqualifying even if
   the total ties.
2. **Evidence localisation** — how often PASS verdicts quoted the intended box
   (your "evidence box ok?" column). A layout that gets the right verdict from
   the wrong box is fragile; it will drift as criteria evolve.
3. **Stability on the borderline artifacts** — fewer verdict flips across the
   three runs. A predictable call on a genuine judgement call beats a coin-flip.
4. **Fewer fields** — less student burden, less empty-box surface for the judge
   to hallucinate into.
5. **Still even → keep the current layout.** This is an *initial* set; a tie is
   itself the finding — the incumbent is fine, ship it, and leave marginal gains
   to the later systematic pass. Don't churn the schema and invalidate the
   repaired suite for no measurable reason.

### 4d. Worked example (illustrative)

`case_design`, C1 (`normal_cases`, `edge_cases`, `reasoning`) vs C2 (adds a
dedicated `traces` box):

| criterion | C1 | C2 |
| --- | --- | --- |
| has_normal_case | 6/6 | 6/6 |
| has_edge_case | 5/6 | 5/6 |
| work_is_shown | 4/6 | 6/6 |
| outputs_are_correct | 6/6 | 4/6 |
| **total** | **21/24** | **21/24** |

Totals tie. Triage the moves: C2 wins `work_is_shown` because the empty `traces`
box makes a missing trace obvious (CD-2). C2 loses `outputs_are_correct` because
separating the trace from its input/output pair lets the judge check against the
student's stated arithmetic instead of re-deriving it, so it misses the wrong
quotient in CD-3. `outputs_are_correct` is the criterion this phase exists to
protect → **keep C1**. Record that C1's `work_is_shown` weakness is real and
feeds a later `work_is_shown` guidance tweak (out of scope here).

### 4e. Record the decision

A short paragraph per phase: candidates tried, the per-criterion table, which
tie-breaker settled it, and any criterion no layout served well.

- [ ] `problem_definition` — decision recorded
- [ ] `case_design` — decision recorded
- [ ] `algorithm_design` — decision recorded

---

## Step 5 — Promote and record

For each phase where the winner differs from the current layout:

1. [ ] Still in sandbox, **Prompt tab**: winning `artifact_fields` in place.
2. [ ] Bump **`version`** in the Prompt tab (`problem_definition` 4→5,
       `case_design` 2→3, `algorithm_design` 2→3).
3. [ ] Header → **Promote to files** (select the phase).
4. [ ] **By hand in `prompts/phases/<phase>.yaml`** (the Studio does not expose
       these):
   - `changelog:` — prepend a `v<N>:` line naming the alternatives compared and
     why this layout won. The Studio changelog box *replaces* rather than
     appends, so editing the YAML directly is safer for the multi-line block.
   - `task_description:` — update the student-facing prose so it names the final
     boxes (it currently enumerates the old ones).
5. [ ] Add an entry to `prompts/CHANGELOG.md` (why, not just what).
6. [ ] `git diff` — the only changed files should be `prompts/phases/*.yaml` and
       `prompts/CHANGELOG.md`. `criteria_version` does **not** change; you did
       not touch criteria.
7. [ ] Save the pilot artifacts + your labels into `cases/suites/<phase>.yaml`
       (convert `met`/`unmet` → `PASS`/`FAIL`; there is no `uncertain` verdict
       now — relabel those to the stricter reading or drop the assertion). This
       becomes the corpus for a later systematic pass.

For each phase where the winner **is** the current layout: record that it was
validated against candidates A/B and move on. No version bump.

---

## Gotchas

- **Two providers.** See Prerequisites — `algorithm_design` calls Anthropic, the
  other two call DeepSeek. A missing key fails only the Run, not the editing.
- **Judge non-determinism.** Verdicts vary run to run; that is why borderline
  artifacts get repeat runs. A layout whose *modal* answer is right but flips
  often is worse than a stable one.
- **Sandbox status is separate** from the real-file status store, so pilot
  verdicts never pollute the saved Rubric tab.
- **`task_description` and `changelog` are hand-edit only** after a promote — the
  Prompt tab round-trips them untouched, so a promoted field change leaves both
  describing the old boxes until you fix them.
- **Keep it to `artifact_fields`.** Anything you notice about criteria or the
  system prompt goes in your notes, not into this pass.

## Rough effort

~half a day: 1h assembling and labelling artifacts, 30–45 min desk-check,
2–3h runs (3 phases × 2 layouts × ~6 artifacts, borderlines ×3), 30 min
decisions and promotion.
