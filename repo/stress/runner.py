"""Stress-test orchestrator (Play 10, steps 1–4 automated; step 4's sign-off and step 5 stay human).

    python -m stress.runner --target workbench                 run every hotspot that is due per the tracker
    python -m stress.runner --target ollama:llama3.1:8b --hotspots 2   run specific hotspots against any model
    python -m stress.runner --target workbench --all           ignore cadence, run everything implemented

Reads cadence / last run from the Stress-Test Tracker (via the caa stress_tracker adapter, so xlsx or CSV).
Writes  stress/results/<date>_<target>.json          one result per hotspot, fixed shape, hashed
        stress/results/tracker_proposal_<date>.csv   proposed tracker rows — the reviewer applies these
Never edits the workbook or the governance CSVs. That is Play 10 step 4, a person.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stress import hotspots  # noqa: E402
from stress.targets import make  # noqa: E402

RESULTS = Path(__file__).parent / "results"


def load_tracker(repo: Path) -> list[dict]:
    import yaml
    from caa.adapters import REGISTRY
    cfg = yaml.safe_load((repo / "audit.yaml").read_text())["sources"].get("stress_tracker", {})
    res = REGISTRY["stress_tracker"](repo, cfg.get("args", {}))
    if res.status != "ok":
        print(f"tracker unavailable: {res.message}"); return []
    return res.records


def due(rows: list[dict]) -> list[int]:
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        n = int(r["n"])
        if n not in hotspots.REGISTRY:
            continue
        lr = r.get("last_run")
        if lr is None or lr == "":
            out.append(n); continue
        try:
            lr_dt = lr if isinstance(lr, datetime) else datetime.fromisoformat(str(lr))
            lr_dt = lr_dt if lr_dt.tzinfo else lr_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            out.append(n); continue
        if r.get("max_days") and (now - lr_dt).days > int(r["max_days"]):
            out.append(n)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="workbench")
    ap.add_argument("--hotspots", default=None, help="comma-separated tracker numbers")
    ap.add_argument("--all", action="store_true", help="run every implemented hotspot regardless of cadence")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    rows = load_tracker(repo)
    by_n = {int(r["n"]): r for r in rows}

    if a.hotspots:
        todo = [int(x) for x in a.hotspots.split(",")]
    elif a.all:
        todo = sorted(hotspots.REGISTRY)
    else:
        todo = due(rows)
    implemented = sorted(hotspots.REGISTRY)
    print(f"target={a.target}  implemented hotspots={implemented}  due={todo}")
    if not todo:
        print("nothing due. Use --all or --hotspots to force."); return 0

    target = make(a.target)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    RESULTS.mkdir(exist_ok=True)
    results, proposals = [], []
    for n in todo:
        fn = hotspots.REGISTRY.get(n)
        if not fn:
            print(f"  #{n}: no runner implemented — stays 'Not run' in the tracker"); continue
        print(f"  #{n} {hotspots.NAMES[n]} …", end=" ", flush=True)
        try:
            r = fn(target, {"results_dir": str(RESULTS)}).to_dict()
        except Exception as e:  # noqa: BLE001
            r = hotspots.HotspotResult(n, hotspots.NAMES[n], target.name, hotspots.now(), "?", 0, 0, "Not run", "High", note=f"runner error: {e}"[:300]).to_dict()
        print(f"{r['result']}  ({r['failed']}/{r['cases']} failed)  risk={r['residual_risk']}" + (f"  note={r['note']}" if r["note"] else ""))
        results.append(r)
        row = by_n.get(n, {})
        cadence_days = int(row.get("max_days") or 100)
        proposals.append({"#": n, "Hotspot": row.get("hotspot") or hotspots.NAMES[n], "Last run": r["run_at"][:10], "Result": r["result"],
                          "Residual risk": r["residual_risk"], "Next run": (datetime.now(timezone.utc) + timedelta(days=cadence_days)).date().isoformat(),
                          "Engine": r["engine"], "Evidence hash": r["evidence_hash"][:16], "Note": r["note"]})

    out = RESULTS / f"{stamp}_{a.target.replace(':', '_').replace('/', '_')}.json"
    out.write_text(json.dumps({"target": a.target, "run_at": stamp, "results": results}, indent=2, default=str))
    prop = RESULTS / f"tracker_proposal_{stamp}.csv"
    with prop.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(proposals[0].keys())); w.writeheader(); w.writerows(proposals)
    print(f"\nresults:  {out}\nproposed tracker rows:  {prop}\nApply the proposal to the Stress-Test Tracker after review (Play 10 step 4), then run the audit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
