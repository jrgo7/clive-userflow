# Artifact-fields pilot — results

Run 2026-09-01/02 via `clive.judge.judge()` called directly (identical code path
to the Studio Run tab). Every corpus artifact, both survivor layouts, judged
twice — once as **`deepseek-v4-flash`**, once as **`deepseek-v4-pro`** — across
all three phases. 108 ok calls, full matrix, ~310k tokens.

Raw per-call data: `artifact-fields-pilot-results.jsonl`. Ground-truth labels:
`artifact-fields-pilot-corpus.yaml`. Tooling: `scripts/run_pilot.py` /
`scripts/score_pilot.py`.

## What changed to make this run possible

`judge()` picked its provider from the global `CLIVE_PROVIDER` only, so
`algorithm_design` (pinned to `claude-opus-5`) silently went to whichever
provider the env var named. Fixed: `Provider` gained `owns_model()` /
`model_prefixes`, and `get_provider(model=...)` now resolves, in order: an
explicit name → the provider that owns the requested model id → `CLIVE_PROVIDER`
as fallback. `judge()` calls it with the phase's `model.id`. 6 new tests in
`tests/test_providers.py`; all 21 tests pass. This is a real fix, not pilot-only
scaffolding — it's in `src/clive/`.

## Token budget note

`deepseek-v4-pro` is markedly more verbose than `deepseek-v4-flash`. Several
calls truncated the verdict JSON at `max_output_tokens: 4000`; `case_design`
cleared at 8000, but `algorithm_design`/`AD-3` needed 16000. `algorithm_design`'s
phase YAML is now set to 8000 (see `prompts/CHANGELOG.md`); a pathological
artifact may still need more.

---

## problem_definition — P1 vs P2

Criteria: `novel_wording`, `concrete_types`, `constraints_noted` · phase-critical: **`novel_wording`**

| Metric | P1 (flash) | P2 (flash) | P1 (pro) | P2 (pro) |
| --- | --- | --- | --- | --- |
| Agreement, overall | 16/18 | 17/18 | 16/18 | 15/18 |
| &nbsp;&nbsp;`novel_wording` **(critical)** | 4/6 | 5/6 | 6/6 | 5/6 |
| &nbsp;&nbsp;`concrete_types` | 6/6 | 6/6 | 6/6 | 6/6 |
| &nbsp;&nbsp;`constraints_noted` | 6/6 | 6/6 | 4/6 | 4/6 |
| False passes (FP) | 2 | 1 | 2 | 3 |
| Quote-not-found | 10 | 3 | 5 | 7 |
| Box count | 3 | 4 | 3 | 4 |

**The pick flips between judge models — no consistent winner.** Flash prefers
P2 by 1; pro prefers P1 by 1. Both gaps are inside the ±3 noise floor either way.

**A real strike against P2, found only under `deepseek-v4-pro`:** on `PD-4` and
`PD-5`, the judge PASSed `constraints_noted` quoting **`"Constraints: (not
provided)"`** as its evidence — the literal empty-box placeholder. It is
treating *the presence of a Constraints field* as satisfying the criterion, not
its content. `P1` has no such field to false-trigger on. This is a specific,
mechanistic failure mode of adding a dedicated-but-often-empty box, not noise.

**Pick: keep P1.** No consistent agreement gain, and the one clear layout-level
effect found is a failure mode in P2.

---

## case_design — C1 vs C3

Criteria: `has_normal_case`, `has_edge_case`, `work_is_shown`, `outputs_are_correct` · phase-critical: **`outputs_are_correct`**

| Metric | C1 (flash) | C3 (flash) | C1 (pro) | C3 (pro) |
| --- | --- | --- | --- | --- |
| Agreement, overall | 21/24 | 23/24 | 20/24 | 22/24 |
| &nbsp;&nbsp;`has_normal_case` | 4/6 | 6/6 | 5/6 | 5/6 |
| &nbsp;&nbsp;`has_edge_case` | 6/6 | 6/6 | 3/6 | 5/6 |
| &nbsp;&nbsp;`work_is_shown` | 6/6 | 6/6 | 6/6 | 6/6 |
| &nbsp;&nbsp;`outputs_are_correct` **(critical)** | 5/6 | 5/6 | 6/6 | 6/6 |
| False fails (FN) | 2 | 0 | 3 | 1 |
| Quote-not-found | 15 | 8 | 9 | 10 |
| Box count | 3 | 2 | 3 | 2 |

**C3 wins by the same +2 margin under both judge models — the only phase where
the pick is stable across models.** The per-criterion story differs by model but
points the same direction both times: under flash, C1's split boxes false-fail
`has_normal_case` on two artifacts (`CD-1`, `CD-2`) that plainly contain a
concrete input + output; under pro, C1's split boxes instead false-fail
`has_edge_case` on the same two artifacts, which explicitly label their boundary
case ("edge case: smallest allowed class size") — the judge misses it once it's
sitting alone in the `edge_cases` box. **Splitting normal/edge cases into
separate boxes costs this judge a clearly-present case, on a different criterion
depending on the model, in both runs.** C3's one miss on each is `CD-5`
(abstract-description artifact) or `CD-1`/`has_normal_case` under pro — a
tighter, more consistent story than C1's.

**`outputs_are_correct` (the phase's reason to exist) ties in both models — no
regression from C3.** And under `deepseek-v4-pro` it goes 6/6 in *both* layouts:
the judge finally computes `100 / 4` and catches `CD-3`'s planted wrong output,
which `deepseek-v4-flash` rubber-stamped in every configuration. See "Model
choice" below.

**Pick: C3.** Fewer boxes, consistently ahead, no critical-criterion cost.

---

## algorithm_design — D1 vs D3

Criteria: `ordered_steps`, `not_c_code`, `inputs_are_consumed`, `state_is_named`, `output_is_produced` · phase-critical: **`not_c_code`**

| Metric | D1 (flash) | D3 (flash) | D1 (pro) | D3 (pro) |
| --- | --- | --- | --- | --- |
| Agreement, overall | 33/35 | 34/35 | 33/35 | 33/35 |
| &nbsp;&nbsp;`ordered_steps` | 6/7 | 7/7 | 6/7 | 6/7 |
| &nbsp;&nbsp;`not_c_code` **(critical)** | 7/7 | 7/7 | 7/7 | 7/7 |
| &nbsp;&nbsp;`inputs_are_consumed` | 6/7 | 6/7 | 6/7 | 6/7 |
| &nbsp;&nbsp;`state_is_named` | 7/7 | 7/7 | 7/7 | 7/7 |
| &nbsp;&nbsp;`output_is_produced` | 7/7 | 7/7 | 7/7 | 7/7 |
| False passes (FP) | 1 | 0 | 1 | 1 |
| False fails (FN) | 1 | 1 | 1 | 1 |
| Evidence localisation (hit/miss) | 14/1 | 23/1 | 14/0 | 22/0 |
| Quote-not-found | 20 | 11 | 21 | 13 |
| Box count | 3 | 2 | 3 | 2 |

**Agreement is a tie** — identical per-criterion on `v4-pro` (both 6/7, 7/7, 6/7,
7/7, 7/7), and only +1 to D3 on flash. The two shared misses are `AD-3`
(`ordered_steps` label FAIL → judge PASS; `inputs_are_consumed` label PASS →
judge FAIL) in *every* layout/model combination — the judge does not reliably
detect "unrecoverable step order" in a prose paragraph, and reads a
correctly-described-but-unordered read loop as a gap. That is a criterion/model
issue; neither layout touches it.

Where D3 separates is **evidence quality**: it gets the judge to quote the
intended box far more often (localisation 22–23 hits vs 14) and produces roughly
half the quote-not-found rate, on both models. Plus one fewer box.

**Pick: D3** — on the tie-breakers (agreement tied → localisation clearly D3 →
fewer fields), not on agreement. Confidence is now solid: the matrix is
complete and the two models agree.

---

## Model choice — a finding independent of field layout

`deepseek-v4-flash` (what `model.id: deepseek-chat` resolves to) does not
reliably compute. It rubber-stamped `CD-3`'s planted wrong output
(`100 / 4 = "30.00"`) in **every** `case_design` configuration tested — both
layouts, meaning the layout choice cannot fix this. `deepseek-v4-pro` caught it
in both layouts. If `case_design`'s `outputs_are_correct` criterion — the one
this phase exists to protect — is going to work at all, the phase needs
`deepseek-v4-pro` (or a comparably capable model), not `deepseek-chat`/flash.
This is a `model.id` decision for the phase YAMLs, separate from and orthogonal
to the field-layout pick above.

Both models show heavy non-verbatim evidence (quote-not-found: roughly a third
to half of all verdicts across the board). That is a `judge_json` /
prompt-instruction concern, not something either field layout fixes.

## Corpus label notes

- **`PD-5` (borderline paraphrase, `novel_wording`)** — under flash it landed
  `PASS` 3/3 in both layouts, which looked like the label was simply too strict.
  Under pro it's genuinely unstable and *layout-sensitive*: P1 majority `FAIL`
  (2/3), P2 majority `PASS` (2/3) — different splits on the identical `summary`
  text depending on what else is in the artifact. That's evidence `PD-5` is
  doing its job as a borderline fixture, not that the label is wrong. Leave it.
- **`CD-1` (clean pass)** — under `deepseek-v4-pro`, `has_normal_case` false-fails
  in *both* C1 and C3, something flash never did. Worth a second look at whether
  the artifact is as unambiguous as intended, independent of layout.

## Reproduce

```
J=docs/artifact-fields-pilot-results.jsonl
uv run python scripts/run_pilot.py $J                                           # each phase on its pinned model.id
PILOT_MODEL=deepseek-v4-flash uv run python scripts/run_pilot.py $J             # force the whole sweep onto one model
PILOT_MODEL=deepseek-v4-pro PILOT_MAX_TOKENS=16000 uv run python scripts/run_pilot.py $J
uv run python scripts/score_pilot.py $J docs/artifact-fields-pilot-results.md
```

`run_pilot.py` is idempotent against the output file: it skips any
`(phase, layout, artifact, run, requested-model)` already recorded `ok`, so
re-running after an error or interruption only fills gaps. `PILOT_ONLY=<phase>`
narrows the sweep. Prune non-ok rows before re-scoring:
`jq -c 'select(.ok)' $J | sponge $J` (or the equivalent Python one-liner).
