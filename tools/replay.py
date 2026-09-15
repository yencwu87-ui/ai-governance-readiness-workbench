#!/usr/bin/env python3
"""WB-044 — replay: every past decision becomes an evaluation case.

The problem this solves
-----------------------
Evaluation rested on 25 hand-authored golden cases and two corpus controls. Expensive to write,
slow to grow, and currently unusable because the corpus labels were argued against a superseded
requirement decomposition. Meanwhile every completed cycle is a labelled example — evidence, the
requirement version in force, the AI proposal, an independent human read, the disagreement, and
a reasoned decision by a named person. That data was being generated as a by-product of doing the
work and then discarded.

Replay re-runs a stored cycle against a different model, prompt or requirement version and
compares the new proposal to what the reviewer actually decided. It turns model selection, prompt
changes and requirement edits from arguments into measurements.

    python tools/replay.py --list
    python tools/replay.py --model llama3.1:8b --limit 20
    python tools/replay.py --model llama3.2 --element-pass combined --json runs/replay.json

Four honesty rules, each of which exists because the obvious shortcut is wrong:

  1. The reviewer's decision is the reference, not the original proposal. Replaying against the
     old proposal measures reproducibility, which is worth knowing and is a different question.
     `--against proposal` asks that question explicitly.

  2. Imported cycles are excluded by default. A record reconstructed from the legacy blob is not
     the same evidence as one written when it happened. `--include-imported` overrides it, and
     the flag appears in the output so a reader knows.

  3. A cycle whose requirement has changed since it was decided is reported `stale`, not scored.
     Same rule as the corpus binding gate: a decision only remains a label while it describes
     the requirement it was argued against.

  4. Below `--min-cases` the accuracy is withheld entirely. A rate over four cases is not a rate,
     and reporting one invites exactly the over-reading this repository exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import events  # noqa: E402
import llm  # noqa: E402

MIN_CASES = 5
ORDER = {"none": 0, "partial": 1, "full": 2}


def requirement_sha(control_id: str) -> str | None:
    try:
        from eval_adapters import requirement_sha as rs
        return rs(control_id)
    except Exception:
        return None


def eligible(include_imported: bool) -> list[dict]:
    out = []
    for s in events.decided():
        decision = s.get("decision") or {}
        if not include_imported and decision.get("imported"):
            continue
        if not s.get("evidence", {}).get("text"):
            continue                                    # nothing to re-run against
        out.append(s)
    return out


def replay_one(s: dict, against: str) -> dict:
    from pipeline import is_error, propose
    from playbook import load_controls
    import glob

    control_id = s["control_id"]
    reference = (s["decision"]["sufficiency"] if against == "decision"
                 else (s.get("proposal") or {}).get("sufficiency"))
    row = {"cycle_id": s["cycle_id"], "control_id": control_id,
           "reference": reference, "reference_from": against,
           "recorded_sha": (s.get("assessment_identity") or {}).get("assessment_id"),
           "stale": False, "error": None}

    # Rule 3 — a decision is a label only while the requirement it was argued against still holds.
    recorded_req = (s.get("decision") or {}).get("requirement_sha") \
        or (s.get("evidence") or {}).get("requirement_sha")
    live_req = requirement_sha(control_id)
    if recorded_req and live_req and recorded_req != live_req:
        row.update(stale=True, recorded_req=recorded_req, live_req=live_req)
        return row

    wb = sorted(glob.glob(str(ROOT / "data" / "*.xlsx")))
    control = None
    for lib, controls in load_controls(wb[0]).items():
        for c in controls:
            if c.id == control_id and (not s.get("framework") or lib == s["framework"]):
                control = c
    if control is None:
        row["error"] = "control not found in the current workbook"
        return row

    with llm.model_for("assess") as model:
        with llm.observe("assess", cycle_id=s["cycle_id"], control_id=control_id):
            proposal = propose(control, s["evidence"])
    row["model"] = model
    if is_error(proposal):
        row["error"] = proposal.get("error", "assessor call failed")
        return row

    row["replayed"] = proposal.get("sufficiency")
    row["agrees"] = row["replayed"] == reference
    if reference in ORDER and row["replayed"] in ORDER:
        row["distance"] = ORDER[row["replayed"]] - ORDER[reference]
        row["adjacent"] = abs(row["distance"]) <= 1
        row["direction"] = ("generous" if row["distance"] > 0
                            else "harsh" if row["distance"] < 0 else "same")
    row["elements"] = [{"element_id": v["element_id"], "status": v["status"]}
                       for v in proposal.get("elementVerdicts") or []]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="override the assess-role model for this run")
    ap.add_argument("--element-pass", choices=["split", "combined", "off"])
    ap.add_argument("--against", choices=["decision", "proposal"], default="decision",
                    help="decision = did the assessor reach what the human decided (accuracy). "
                         "proposal = does it reproduce its own earlier output (reproducibility).")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-cases", type=int, default=MIN_CASES)
    ap.add_argument("--include-imported", action="store_true")
    ap.add_argument("--list", action="store_true", help="show eligible cycles and stop")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    if a.model:
        os.environ["WB_MODEL_ASSESS"] = a.model
    if a.element_pass:
        os.environ["WB_ELEMENT_PASS"] = a.element_pass

    cases = eligible(a.include_imported)
    if a.limit:
        cases = cases[:a.limit]

    if a.list:
        for s in cases:
            d = s["decision"]
            print(f"{s['cycle_id']:32} {s['control_id']:10} decided {d['sufficiency']:8} "
                  f"by {s.get('decided_by', '?')}")
        print(f"\n{len(cases)} eligible cycle(s)")
        return 0

    if not cases:
        print("No eligible cycles. Replay needs completed cycles with bound evidence —\n"
              "run some assessments through wb.py or the app first, or migrate the legacy\n"
              "blob with `python wb.py migrate data/assessments.json --include-imported`.")
        return 0

    print(f"replaying {len(cases)} cycle(s) against the {a.against}   "
          f"model {llm.model_name('assess')}   elements {os.environ.get('WB_ELEMENT_PASS', 'split')}\n")
    rows = []
    for s in cases:
        r = replay_one(s, a.against)
        rows.append(r)
        if r["stale"]:
            print(f"  {r['control_id']:10} {r['cycle_id'][:22]:24} STALE — requirement changed "
                  f"since the decision")
        elif r["error"]:
            print(f"  {r['control_id']:10} {r['cycle_id'][:22]:24} ERROR — {r['error'][:44]}")
        else:
            mark = "=" if r["agrees"] else r.get("direction", "?")
            print(f"  {r['control_id']:10} {r['cycle_id'][:22]:24} {r['reference']:8} -> "
                  f"{r['replayed']:8} {mark}")

    scored = [r for r in rows if not r["stale"] and not r["error"] and "agrees" in r]
    stale = [r for r in rows if r["stale"]]
    errored = [r for r in rows if r["error"]]

    print("\n--- summary ---")
    print(f"eligible {len(rows)}   scored {len(scored)}   stale {len(stale)}   errors {len(errored)}")
    if stale:
        print("Stale cycles are not scored. Their decisions were argued against a requirement "
              "that has\nsince changed, so agreement with them measures nothing.")

    result = {"against": a.against, "model": llm.model_name("assess"),
              "element_pass": os.environ.get("WB_ELEMENT_PASS", "split"),
              "include_imported": a.include_imported,
              "eligible": len(rows), "scored": len(scored), "stale": len(stale),
              "errors": len(errored), "rows": rows}

    if len(scored) < a.min_cases:
        print(f"\nNOT_TESTABLE — {len(scored)} scored case(s), below the floor of {a.min_cases}. "
              f"No accuracy is\nreported. A rate over a handful of cases is not a rate.")
        result["status"] = "NOT_TESTABLE"
    else:
        agree = sum(r["agrees"] for r in scored)
        adjacent = sum(r.get("adjacent", False) for r in scored)
        direction = Counter(r.get("direction") for r in scored if not r["agrees"])
        baseline = Counter(r["reference"] for r in scored).most_common(1)[0]
        result.update(status="scored",
                      accuracy=round(agree / len(scored), 3),
                      adjacent_accuracy=round(adjacent / len(scored), 3),
                      constant_baseline=round(baseline[1] / len(scored), 3),
                      baseline_label=baseline[0],
                      disagreement_direction=dict(direction))
        print(f"accuracy            {result['accuracy']:.1%}  ({agree} of {len(scored)})")
        print(f"adjacent            {result['adjacent_accuracy']:.1%}")
        print(f"constant baseline   {result['constant_baseline']:.1%}  "
              f"(always answering '{baseline[0]}')")
        margin = result["accuracy"] - result["constant_baseline"]
        print(f"margin over baseline {margin:+.1%}"
              + ("   WORSE THAN A CONSTANT ANSWER" if margin <= 0 else ""))
        if direction:
            print(f"when it disagrees   {dict(direction)}")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(result, indent=1, default=str))
        print(f"\nwritten: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
