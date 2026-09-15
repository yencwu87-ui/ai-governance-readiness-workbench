"""Sweep min_ratio through retrieval only — no assessor, no LLM calls.

Shows how many controls would receive evidence at each setting, overall and
per library, so a value can be chosen from data rather than from the slider.

    python eval/ratio_sweep.py --folder <evidence folder> \
        --playbook data/AI_Governance_Playbook_..._v3_CSA_backref.xlsx

ratio 0.0 with min_score 0.0 reproduces the pre-change behaviour exactly
(every control receives k chunks), so that row is the regression control.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import index_folder, match_controls  # noqa: E402
from playbook import load_controls  # noqa: E402

GRID = [0.0, 0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--playbook", required=True)
    ap.add_argument("--scope", default=None,
                    help="comma-separated libraries (default: all)")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--min-score", type=float, default=0.0)
    a = ap.parse_args()

    by_lib = load_controls(a.playbook)
    libs = ([s.strip() for s in a.scope.split(",")] if a.scope else sorted(by_lib))
    in_scope = [c for lib in libs for c in by_lib.get(lib, [])]
    print(f"{len(in_scope)} controls across {libs}")

    print(f"indexing {a.folder} ...")
    index, _signals = index_folder(a.folder)
    print(f"  {len(index.chunks)} chunks\n")

    print(f"k={a.k}  min_score={a.min_score}")
    print("  ratio   with evidence   no evidence   avg chunks")
    per_lib = {}
    for r in GRID:
        matches = match_controls(index, in_scope, min_ratio=r,
                                 min_score=a.min_score, k=a.k)
        n = len(matches)
        avg = (sum(len(v) for v in matches.values()) / len(in_scope)) if in_scope else 0
        note = "   <- reproduces old behaviour" if r == 0.0 else ""
        print(f"  {r:5.2f}   {n:4d}          {len(in_scope) - n:4d}         {avg:.2f}{note}")
        per_lib[r] = {
            lib: sum(1 for c in by_lib.get(lib, []) if c.key in matches)
            for lib in libs
        }

    print("\ncontrols WITH evidence, by library:")
    header = "  ratio  " + "".join(f"{lib[:12]:>14}" for lib in libs)
    print(header)
    for r in GRID:
        row = "".join(f"{per_lib[r][lib]:>8d} /{len(by_lib.get(lib, [])):>4d}" for lib in libs)
        print(f"  {r:5.2f}  {row}")

    print("\nRead this as: the row where controls start dropping out is where the")
    print("gate begins to bind. Pick a value below the point where libraries")
    print("diverge sharply — divergence means the gate is measuring control")
    print("wordiness, not evidence quality. Spot-check a few dropped controls")
    print("against the folder before trusting any 'no evidence' result.")


if __name__ == "__main__":
    main()
