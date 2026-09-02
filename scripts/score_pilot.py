"""Score the pilot: read results.jsonl + corpus labels, emit a Markdown report.

Groups by (phase, layout, judge-model). One scorecard per (phase, model)
comparing the two survivor layouts; a flash-vs-pro note per phase; a
disagreement-triage table and a full per-assertion appendix."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_pilot import CORPUS, LAYOUTS, PROBLEM  # noqa: E402
from clive import prompts  # noqa: E402

JSONL = Path(sys.argv[1])
OUT = Path(sys.argv[2])

PHASE_ORDER = ["problem_definition", "case_design", "algorithm_design"]
SURV = {"problem_definition": ["P1", "P2"], "case_design": ["C1", "C3"], "algorithm_design": ["D1", "D3"]}
KEY_CRIT = {
    "problem_definition": "novel_wording",
    "case_design": "outputs_are_correct",
    "algorithm_design": "not_c_code",
}
INTENDED = {
    "problem_definition": {
        "novel_wording": {"*": {"summary"}},
        "concrete_types": {"*": {"inputs", "outputs"}},
        "constraints_noted": {"P1": {"inputs"}, "P2": {"constraints"}},
    },
    "case_design": {
        "has_normal_case": {"C1": {"normal_cases"}, "C3": {"cases"}},
        "has_edge_case": {"C1": {"edge_cases"}, "C3": {"cases"}},
        "work_is_shown": {"C1": {"normal_cases", "edge_cases"}, "C3": {"cases"}},
        "outputs_are_correct": {"C1": {"normal_cases", "edge_cases"}, "C3": {"cases"}},
    },
    "algorithm_design": {
        "ordered_steps": {"*": {"steps"}},
        "not_c_code": {"*": {"steps"}},
        "inputs_are_consumed": {"*": {"steps"}},
        "state_is_named": {"*": {"state"}},
        "output_is_produced": {"D1": {"output_step"}, "D3": {"steps"}},
    },
}


def norm(s):
    return " ".join(str(s).split()).lower()


def intended_for(phase, layout, crit):
    m = INTENDED[phase][crit]
    return m.get(layout) or m.get("*") or set()


def rebuild_artifact(phase, layout, art_entry):
    base_fields = prompts.load_phase(phase)["artifact_fields"]
    _, artifact = LAYOUTS[phase][layout](art_entry["fields"], base_fields)
    return artifact


def which_fields(artifact, quote):
    q = norm(quote)
    return [k for k, v in artifact.items() if q and q in norm(v)]


def labels_for(phase, art_id):
    for a in CORPUS[phase]["artifacts"]:
        if a["id"] == art_id:
            return a["labels"], a.get("borderline", []), a.get("role", "")
    raise KeyError(art_id)


def model_of(r):
    return r.get("req_model") or r.get("model") or "?"


def score_cell(phase, layout, model, by, crits, triage, appendix):
    m = dict(
        per_ok=Counter(), per_tot=Counter(), tp=0, tn=0, fp=0, fn=0,
        loc_hit=0, loc_miss=0, qnf=0, id_warn=0, split=0, box=None, unscored=0,
    )
    for a in CORPUS[phase]["artifacts"]:
        art_id = a["id"]
        recs = [r for r in by[(phase, layout, model, art_id)] if r["ok"]]
        labels, _bl, role = labels_for(phase, art_id)
        if recs:
            m["box"] = len(recs[0]["fields"])
            m["id_warn"] += sum(len(r["missing_ids"]) + len(r["unexpected_ids"]) for r in recs)
        artifact = rebuild_artifact(phase, layout, a)
        for crit in crits:
            label = labels[crit]
            verds = [next((x for x in r["verdicts"] if x["criterion_id"] == crit), None) for r in recs]
            verds = [v for v in verds if v]
            if not verds:
                m["unscored"] += 1
                continue
            calls = [v["verdict"] for v in verds]
            maj = Counter(calls).most_common(1)[0][0]
            m["per_tot"][crit] += 1
            agree = maj == label
            if agree:
                m["per_ok"][crit] += 1
            if maj == "PASS" and label == "PASS":
                m["tp"] += 1
            elif maj == "FAIL" and label == "FAIL":
                m["tn"] += 1
            elif maj == "PASS" and label == "FAIL":
                m["fp"] += 1
            else:
                m["fn"] += 1
            if len(calls) == 3 and len(set(calls)) > 1:
                m["split"] += 1
            rep = next((v for v in verds if v["verdict"] == maj), verds[0])
            ev = rep.get("evidence", "") or ""
            if ev:
                if not rep.get("evidence_found", False):
                    m["qnf"] += 1
                else:
                    got = which_fields(artifact, ev)
                    if got and (set(got) & intended_for(phase, layout, crit)):
                        m["loc_hit"] += 1
                    elif got:
                        m["loc_miss"] += 1
            ev_from = ("QUOTE-NOT-FOUND" if ev and not rep.get("evidence_found", False)
                       else "/".join(which_fields(artifact, ev)) or ("(no quote)" if not ev else "(elsewhere)"))
            appendix.append(f"| {phase} | {model} | {layout} | {art_id} | {crit} | {label} | "
                            f"{maj} ({'/'.join(calls)}) | {'agree' if agree else 'DISAGREE'} | {ev_from} |")
            if not agree:
                triage.append(dict(
                    phase=phase, model=model, layout=layout, artifact=art_id, role=role,
                    crit=crit, label=label, maj=maj, calls=calls,
                    ev_from=which_fields(artifact, ev) if ev else [],
                    qnf=(bool(ev) and not rep.get("evidence_found", False)),
                    want=sorted(intended_for(phase, layout, crit)),
                    ev=ev, key=(crit == KEY_CRIT[phase]),
                ))
    return m


def main():
    rows = [json.loads(l) for l in JSONL.read_text().splitlines() if l.strip()]
    ok = [r for r in rows if r["ok"]]
    errs = [r for r in rows if not r["ok"]]
    by = defaultdict(list)
    for r in rows:
        by[(r["phase"], r["layout"], model_of(r), r["artifact"])].append(r)
    models_seen = sorted({model_of(r) for r in ok})

    out = ["# Artifact-fields pilot — results\n"]
    out.append(f"Source `{JSONL.name}` · problem `{PROBLEM['id']}` · labels "
               f"`artifact-fields-pilot-corpus.yaml`.\n")
    toks = sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in ok)
    out.append(f"{len(ok)} ok calls · {len(errs)} errors · judge models: "
               f"{', '.join(models_seen)} · {toks:,} tokens.\n")
    if errs:
        out.append("**Errors:** " + "; ".join(
            f"{e['phase']}/{e['layout']}/{e['artifact']} r{e['run']} [{model_of(e)}]: "
            f"{e['error'][:120]}" for e in errs[:12]) + "\n")

    triage, appendix = [], []

    for phase in PHASE_ORDER:
        pmodels = [m for m in models_seen if any(
            r["phase"] == phase for r in ok if model_of(r) == m)]
        out.append(f"\n## {phase}\n")
        if not pmodels:
            out.append("_No successful runs._\n")
            continue
        crits = [c["id"] for c in prompts.load_criteria(phase)["criteria"]]
        key = KEY_CRIT[phase]
        out.append(f"Criteria: {', '.join(crits)} · phase-critical: **{key}**\n")

        A, B = SURV[phase]
        cards = {}
        for model in pmodels:
            sa = score_cell(phase, A, model, by, crits, triage, appendix)
            sb = score_cell(phase, B, model, by, crits, triage, appendix)
            cards[model] = (sa, sb)
            out.append(f"\n### judge = {model}\n")
            out.append(f"| Metric | {A} | {B} | Better |")
            out.append("| --- | --- | --- | --- |")
            ta, tb = sum(sa["per_ok"].values()), sum(sb["per_ok"].values())
            na, nb = sum(sa["per_tot"].values()), sum(sb["per_tot"].values())
            out.append(f"| Agreement, overall | {ta}/{na} | {tb}/{nb} | higher |")
            for c in crits:
                mk = " **(critical)**" if c == key else ""
                out.append(f"| &nbsp;&nbsp;{c}{mk} | {sa['per_ok'][c]}/{sa['per_tot'][c]} "
                           f"| {sb['per_ok'][c]}/{sb['per_tot'][c]} | higher |")
            out.append(f"| False passes (FP) | {sa['fp']} | {sb['fp']} | lower — weighted worse |")
            out.append(f"| False fails (FN) | {sa['fn']} | {sb['fn']} | lower |")
            out.append(f"| Evidence localisation (hit/miss) | {sa['loc_hit']}/{sa['loc_miss']} "
                       f"| {sb['loc_hit']}/{sb['loc_miss']} | more hit, less miss |")
            out.append(f"| Quote-not-found | {sa['qnf']} | {sb['qnf']} | lower |")
            out.append(f"| Missing/invented id | {sa['id_warn']} | {sb['id_warn']} | lower |")
            out.append(f"| Borderline split (2–1) | {sa['split']} | {sb['split']} | lower |")
            out.append(f"| Box count | {sa['box']} | {sb['box']} | fewer |")
            if sa["unscored"] or sb["unscored"]:
                out.append(f"| _unscored (errored runs)_ | {sa['unscored']} | {sb['unscored']} | |")
            out.append("")
            gap = tb - ta
            out.append(f"Gap {A}→{B}: {gap:+d} assertions. Noise ≈ ±3.\n")

        if len(pmodels) == 2:
            m1, m2 = pmodels
            out.append(f"\n### {m1} vs {m2} — does the pick change?\n")
            for lay in (A, B):
                s1 = cards[m1][0 if lay == A else 1]
                s2 = cards[m2][0 if lay == A else 1]
                o1 = f"{sum(s1['per_ok'].values())}/{sum(s1['per_tot'].values())}"
                o2 = f"{sum(s2['per_ok'].values())}/{sum(s2['per_tot'].values())}"
                out.append(f"- **{lay}**: {m1} {o1} (FP {s1['fp']}, QNF {s1['qnf']}) · "
                           f"{m2} {o2} (FP {s2['fp']}, QNF {s2['qnf']})")
            out.append("")

    out.append("\n## Disagreements to triage\n")
    out.append("Classify: **misrouted** (wrong box / quote-not-found — counts against the layout) · "
               "**right-box-wrong-call** (criterion/model issue) · **label-wrong** (fix corpus).\n")
    out.append("| phase | judge | layout | artifact (role) | criterion | label | majority (runs) | from → intended | quote |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for t in sorted(triage, key=lambda x: (PHASE_ORDER.index(x["phase"]), x["model"], x["layout"], x["artifact"], x["crit"])):
        frm = "QUOTE-NOT-FOUND" if t["qnf"] else ("/".join(t["ev_from"]) or "(none)")
        q = t["ev"].replace("\n", " ").strip()
        q = (q[:70] + "…") if len(q) > 70 else (q or "—")
        star = " ⚠" if t["key"] else ""
        out.append(f"| {t['phase']} | {t['model']} | {t['layout']} | {t['artifact']} ({t['role']}) "
                   f"| {t['crit']}{star} | {t['label']} | {t['maj']} ({'/'.join(t['calls'])}) "
                   f"| {frm} → {'/'.join(t['want'])} | {q} |")
    out.append(f"\n⚠ = phase-critical criterion. {len(triage)} disagreements.\n")

    out.append("\n## Full per-assertion appendix\n")
    out.append("| phase | judge | layout | artifact | criterion | label | majority (runs) | result | evidence from |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    out.extend(appendix)

    OUT.write_text("\n".join(out) + "\n")
    print("wrote", OUT, f"· {len(ok)} ok, {len(errs)} err, {len(triage)} disagreements, models={models_seen}")


if __name__ == "__main__":
    main()
