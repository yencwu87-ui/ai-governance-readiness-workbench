"""Headless scan: python run_scan.py <folder> [--scope MAS,SAFR] [--min-ratio 0.35] [--k 3]
Writes proposals to data/proposals_<date>.json and a Markdown gap analysis. Records nothing to the playbook."""
import argparse
import datetime as dt
import json
from pathlib import Path

from pipeline import gap_analysis, run_scan
from playbook import load_controls
from scanner import MIN_RATIO, MIN_SCORE, TOP_K

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--scope", default="MAS,MGF Agentic,SAFR")
ap.add_argument("--min-ratio", type=float, default=MIN_RATIO,
                help="keep a chunk if it scores at least this fraction of the "
                     "control's best-matching chunk (0-1)")
ap.add_argument("--min-score", type=float, default=MIN_SCORE,
                help="absolute BM25 floor. Note: before the relative gate was "
                     "introduced this flag was the only threshold and never "
                     "bound in practice, so a recorded --min-score from an "
                     "earlier run did not affect that run's findings.")
ap.add_argument("--k", type=int, default=TOP_K,
                help="max chunks per control passed to the assessor")
ap.add_argument("--playbook", default=None)
a = ap.parse_args()

xlsx = Path(a.playbook) if a.playbook else next(Path("data").glob("*.xlsx"))
controls = load_controls(xlsx)
scope = [s.strip() for s in a.scope.split(",")]
in_scope = [c for lib in scope for c in controls.get(lib, [])]
print(f"Playbook: {xlsx.name} | scope: {scope} | {len(in_scope)} controls | folder: {a.folder}")
print(f"Retrieval: min_ratio={a.min_ratio} min_score={a.min_score} k={a.k}")

evidence, proposals = run_scan(
    a.folder, in_scope,
    min_ratio=a.min_ratio,
    min_score=a.min_score,
    k=a.k,
    progress=lambda n, t, name: print(f"  reading {name}"),
)
print(f"\nProposals for {len(proposals)} controls; {len(in_scope) - len(proposals)} had no matching evidence.\n")
for c in in_scope:
    p = proposals.get(c.key)
    if p:
        print(f"{c.id:<10} {p['sufficiency']:<8} m{p['proposedMaturity']}  {'; '.join(p['flags']) or ''}")

stamp = dt.date.today().isoformat()
Path("data").mkdir(exist_ok=True)
# Retrieval settings decide which evidence each control was assessed on, so they
# are part of the run record, not incidental CLI state.
run_params = {"min_ratio": a.min_ratio, "min_score": a.min_score, "k": a.k,
              "folder": a.folder, "scope": scope, "playbook": xlsx.name,
              "at": dt.datetime.now().isoformat(timespec="seconds")}
Path(f"data/proposals_{stamp}.json").write_text(json.dumps(
    {"run_params": run_params, "evidence": evidence, "proposals": proposals},
    indent=1, default=str))
rows = gap_analysis(in_scope, proposals, {})
md = ["# Gap analysis (proposed, unreviewed)\n",
      f"Folder: {a.folder}  \nDate: {stamp}  \n"
      f"Retrieval: min_ratio={a.min_ratio}, min_score={a.min_score}, k={a.k}\n",
      "| Control | Library | Finding | Gaps | Suggested action | Owner |", "|---|---|---|---|---|---|"]
md += [f"| {r['Control']} | {r['Library']} | {r['Finding']} | {r['Gaps']} | {r['Suggested action']} | {r['Owner']} |" for r in rows]
Path(f"data/gap_analysis_{stamp}.md").write_text("\n".join(md))
print(f"\nWrote data/proposals_{stamp}.json and data/gap_analysis_{stamp}.md. Nothing was written to the playbook.")
