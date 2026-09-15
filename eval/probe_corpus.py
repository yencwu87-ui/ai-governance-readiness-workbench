#!/usr/bin/env python3
"""Score the assessor against the constructed corpus.

The corpus lives in eval/corpus/<CONTROL>/ as <CONTROL>_a.md, _b.md, _c.md, with the label
fixed at authoring time and recorded in LABELS.md alongside. The suffix carries the expected
rating: a = full, b = partial, c = none.

LABELS.md is never passed to the assessor. Documents are read directly rather than scanned,
so this measures the assessor, not retrieval.

Usage, from repo/ with the venv active:
    python eval/probe_corpus.py                 # every control in eval/corpus/
    python eval/probe_corpus.py M3.6 M3.12      # named controls only
    python eval/probe_corpus.py --json          # machine-readable, for keeping a run history

Record the score with the model and the prompt hash. A prompt change makes earlier scores
incomparable, so they are not a trend unless those two match.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assessor import assess, model_name  # noqa: E402
from requirements_overlay import apply_overlay, load_overlay  # noqa: E402
from playbook import load_controls  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus"
WORKBOOK = Path("data/AI_Governance_Playbook_MGF_SAFR_FINAL_v3_CSA_backref.xlsx")
ORDER = {"none": 0, "partial": 1, "full": 2}


def expected_labels(control_dir: Path) -> dict[str, str]:
    """Derive the expected label per document from that control's element matrix.

    The label is a consequence of the element facts, not a statement: all applicable elements
    evidenced = full, some = partial, none = none. Elements marked `lane: b` are excluded -
    they are tested by a control pack, not judged from documents.

    Until 2026-09-10 this was hardcoded as {a: full, b: partial, c: none} from the filename
    suffix. That convention broke as soon as the requirement gained elements the documents did
    not evidence: M3.6_a derives to `partial`, and the probe was scoring a correct `partial`
    as a miss against a stale `full`.
    """
    import yaml
    mp = control_dir / "elements.yaml"
    if not mp.exists():
        raise SystemExit(f"{mp} not found. The expected labels are derived from it; there is no "
                         f"filename convention to fall back on.")
    m = yaml.safe_load(mp.read_text())
    out = {}
    for doc in ("a", "b", "c"):
        vals = [e[doc] for e in m["elements"] if e.get("lane", "a") != "b" and doc in e]
        if "?" in vals:
            continue                      # undecided: excluded from scoring, reported separately
        y, n = vals.count("Y"), vals.count("N")
        out[doc] = "full" if n == 0 else "none" if y == 0 else "partial"
    return out


def controls_by_id(workbook: Path) -> dict:
    by_lib = load_controls(str(workbook))
    summary = apply_overlay(by_lib, load_overlay())
    if summary["applied"]:
        print(f"requirements overlay: {summary['applied']} control(s) using written requirements")
    if summary["unmatched"]:
        print(f"!! overlay names controls not in the workbook: {', '.join(summary['unmatched'])}")
    out = {}
    for lst in by_lib.values():
        for c in lst:
            out[c.id.split()[0].rstrip("\u2605").strip()] = c
    return out


def run(names: list[str], workbook: Path) -> dict:
    by_id = controls_by_id(workbook)
    dirs = [CORPUS / n for n in names] if names else sorted(p for p in CORPUS.iterdir() if p.is_dir())
    results, hits, over, under = [], 0, 0, 0

    for d in dirs:
        c = by_id.get(d.name)
        if not c:
            print(f"!! control {d.name} not in the workbook — skipped", file=sys.stderr)
            continue
        labels = expected_labels(d)
        skipped = [s for s in "abc" if s not in labels]
        if skipped:
            print(f"!! {d.name}: {', '.join(d.name + '_' + s for s in skipped)} have undecided "
                  f"elements and are excluded from scoring", file=sys.stderr)
        for p in sorted(d.glob(f"{d.name}_*.md")):
            exp = labels.get(p.stem[-1])
            if not exp:
                continue
            out = assess(c, p.read_text())
            got = out.get("sufficiency")
            ok = got == exp
            hits += ok
            if not ok:
                over += ORDER[got] > ORDER[exp]
                under += ORDER[got] < ORDER[exp]
            results.append({
                "control": d.name, "doc": p.name, "expected": exp, "got": got,
                "maturity": out.get("proposedMaturity"), "excerpt": bool(out.get("excerpt")),
                "gaps": out.get("gaps", []), "flags": out.get("flags", []),
                "artefacts": c.artefacts,
            })
    import yaml as _y
    unconfirmed = 0
    for d in dirs:
        mp = d / "elements.yaml"
        if mp.exists():
            unconfirmed += sum(1 for e in _y.safe_load(mp.read_text())["elements"]
                               if e.get("decided_by") == "claude-unconfirmed")
    return {"model": model_name(), "n": len(results), "correct": hits, "unconfirmed": unconfirmed,
            "over_credit": over, "under_credit": under, "results": results}


def report(r: dict) -> None:
    control = None
    for x in r["results"]:
        if x["control"] != control:
            control = x["control"]
            print(f"\n=== {control}   artefacts: {x['artefacts']!r}")
        mark = "OK  " if x["expected"] == x["got"] else "MISS"
        print(f"{mark} {x['doc']:14} expected={x['expected']:8} got={str(x['got']):8} m{x['maturity']}")
        if x["expected"] != x["got"]:
            for g in x["gaps"]:
                print(f"       gap: {g}")
        for f in x["flags"]:
            print(f"       flag: {f}")
    print(f"\n{r['correct']}/{r['n']} correct   over-credit {r['over_credit']}   "
          f"under-credit {r['under_credit']}   model {r['model']}")

    # Constant baseline. The corpus is one full, one partial and one none per control, so
    # answering the same thing every time scores exactly 1/3. Any run at or below that is
    # not discriminating, whatever the headline says.
    from collections import Counter
    exp = Counter(x["expected"] for x in r["results"])
    if exp:
        base = max(exp.values()) / sum(exp.values())
        margin = r["correct"] / r["n"] - base
        print(f"constant baseline {base:.0%} (always-{exp.most_common(1)[0][0]}) - "
              + ("this run is BELOW it" if margin < 0 else f"{margin:+.0%} against it"))
    print("A score is comparable only to runs with the same model and prompt.")
    if r.get("unconfirmed"):
        print(f"CAVEAT: {r['unconfirmed']} element(s) across this run are marked "
              f"decided_by: claude-unconfirmed - decided by Claude on documents Claude wrote. "
              f"Those labels measure consistency, not accuracy, until a reviewer confirms them.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("controls", nargs="*", help="control ids, e.g. M3.6 M3.12")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--workbook", default=str(WORKBOOK))
    a = ap.parse_args()
    res = run(a.controls, Path(a.workbook))
    print(json.dumps(res, indent=2)) if a.json else report(res)
    sys.exit(0 if res["n"] else 1)
