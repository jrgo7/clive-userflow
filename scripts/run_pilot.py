"""Run the artifact-fields pilot: each corpus artifact through the two survivor
layouts per phase, judged via clive.judge.judge(). Streams JSONL to argv[1]."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

import yaml

from clive import judge, prompts

ROOT = Path("/home/jrgo/src/thesis/clive-userflow")
CORPUS = yaml.safe_load((ROOT / "docs/artifact-fields-pilot-corpus.yaml").read_text())
OUT = Path(sys.argv[1])
PROBLEM = prompts.load_problem("grade_average")


def get_field(base, id_, label=None):
    for f in base:
        if f["id"] == id_:
            g = dict(f)
            if label:
                g["label"] = label
            return g
    return {"id": id_, "label": label or id_, "hint": "", "rows": 6}


def nonempty(*vals):
    return [v.strip() for v in vals if v and v.strip()]


def append_step(steps_text, extra):
    lines = steps_text.rstrip().splitlines()
    nums = [int(m.group(1)) for ln in lines if (m := re.match(r"\s*(\d+)\.", ln))]
    if nums:
        return steps_text.rstrip() + f"\n{max(nums) + 1}. {extra.strip()}"
    return steps_text.rstrip() + "\n\n" + extra.strip()


LAYOUTS = {
    "problem_definition": {
        "P1": lambda a, base: (
            [get_field(base, "summary"), get_field(base, "inputs"), get_field(base, "outputs")],
            {
                "summary": a["summary"],
                "inputs": "\n".join(nonempty(a.get("inputs", ""), a.get("constraints", ""))),
                "outputs": a["outputs"],
            },
        ),
        "P2": lambda a, base: (
            [
                get_field(base, "summary"),
                get_field(base, "inputs"),
                get_field(base, "outputs"),
                get_field(base, "constraints", "Constraints"),
            ],
            {k: a.get(k, "") for k in ("summary", "inputs", "outputs", "constraints")},
        ),
    },
    "case_design": {
        "C1": lambda a, base: (
            [get_field(base, "normal_cases"), get_field(base, "edge_cases"), get_field(base, "reasoning")],
            {k: a.get(k, "") for k in ("normal_cases", "edge_cases", "reasoning")},
        ),
        "C3": lambda a, base: (
            [
                {"id": "cases", "label": "Cases", "hint": get_field(base, "normal_cases").get("hint", ""), "rows": 10},
                get_field(base, "reasoning"),
            ],
            {
                "cases": "\n\n".join(nonempty(a.get("normal_cases", ""), a.get("edge_cases", ""))),
                "reasoning": a.get("reasoning", ""),
            },
        ),
    },
    "algorithm_design": {
        "D1": lambda a, base: (
            [get_field(base, "steps"), get_field(base, "state"), get_field(base, "output_step")],
            {k: a.get(k, "") for k in ("steps", "state", "output_step")},
        ),
        "D3": lambda a, base: (
            [get_field(base, "steps"), get_field(base, "state")],
            {
                "steps": append_step(a["steps"], a["output_step"])
                if a.get("output_step", "").strip()
                else a["steps"],
                "state": a.get("state", ""),
            },
        ),
    },
}


def judge_with_retry(*args, **kw):
    for attempt in range(4):
        try:
            return judge.judge(*args, **kw)
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            transient = "rate limit" in msg or "429" in msg or "overloaded" in msg or "timeout" in msg
            if transient and attempt < 3:
                time.sleep(20 * (attempt + 1))
                continue
            raise


def load_done(path):
    """(phase, layout, artifact, run, req_model) tuples already recorded ok."""
    done = set()
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("ok"):
            continue
        req = r.get("req_model") or r.get("model")
        done.add((r["phase"], r["layout"], r["artifact"], r["run"], req))
    return done


def main():
    only = os.environ.get("PILOT_ONLY")
    force_model = os.environ.get("PILOT_MODEL")  # override the phase's model.id
    force_max_tokens = os.environ.get("PILOT_MAX_TOKENS")  # override model.max_output_tokens
    phases = {k: v for k, v in LAYOUTS.items() if not only or k == only}
    already = load_done(OUT)

    done = 0
    skipped = 0
    for phase_name, layouts in phases.items():
        base_phase = prompts.load_phase(phase_name)
        base_fields = base_phase["artifact_fields"]
        crits = prompts.load_criteria(phase_name)["criteria"]
        req_model = force_model or base_phase.get("model", {}).get("id")
        for layout_name, fn in layouts.items():
            for art in CORPUS[phase_name]["artifacts"]:
                fields, artifact = fn(art["fields"], base_fields)
                pv = dict(base_phase)
                pv["artifact_fields"] = fields
                if force_model or force_max_tokens:
                    pv["model"] = dict(base_phase.get("model", {}))
                    if force_model:
                        pv["model"]["id"] = force_model
                    if force_max_tokens:
                        pv["model"]["max_output_tokens"] = int(force_max_tokens)
                nruns = 3 if art.get("borderline") else 1
                for run_i in range(1, nruns + 1):
                    if (phase_name, layout_name, art["id"], run_i, req_model) in already:
                        skipped += 1
                        continue
                    rec = {
                        "phase": phase_name,
                        "layout": layout_name,
                        "artifact": art["id"],
                        "run": run_i,
                        "req_model": req_model,
                        "fields": [f["id"] for f in fields],
                        "ts": round(time.time(), 1),
                    }
                    try:
                        res = judge_with_retry(pv, PROBLEM, artifact, crits, attempt=1)
                        rec.update(
                            ok=True,
                            model=res["model"],
                            usage=res["usage"],
                            verdicts=res["verdicts"],
                            missing_ids=res["missing_ids"],
                            unexpected_ids=res["unexpected_ids"],
                        )
                    except Exception as e:  # noqa: BLE001
                        rec.update(ok=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc())
                    with OUT.open("a") as fh:
                        fh.write(json.dumps(rec) + "\n")
                    done += 1
                    tag = "OK " if rec["ok"] else "ERR"
                    verds = [f"{v['criterion_id']}={v['verdict']}" for v in rec.get("verdicts", [])]
                    print(f"[{done:3}] {req_model:18} {phase_name:18} {layout_name} {art['id']:6} r{run_i} {tag} {verds}", flush=True)
    print(f"DONE  ran={done}  skipped(existing)={skipped}", flush=True)


if __name__ == "__main__":
    main()
