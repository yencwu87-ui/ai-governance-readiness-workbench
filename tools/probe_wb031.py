#!/usr/bin/env python3
"""WB-031 live probe — does the assessor actually return usable element verdicts?

The deterministic tests prove the validators behave. They cannot tell you whether the model
you run returns a verdict per element at all. If it returns none, every element comes back
`unset`, the compare block correctly reports that nothing was compared, and the feature is
dead without anything looking broken. This script is how you find that out before relying on it.

Usage
-----
    # whatever provider you normally assess with
    ASSESSOR_PROVIDER=ollama OLLAMA_MODEL=llama3.2 python tools/probe_wb031.py
    python tools/probe_wb031.py --controls M3.6 M3.12 --evidence eval/corpus
    python tools/probe_wb031.py --json runs/wb031_probe.json

What to look at, in order of how badly it matters
-------------------------------------------------
  unset_rate        the number that decides whether WB-031 works at all. Anything much above
                    zero means the model is not answering per element and the comparison will
                    be thin. Fix the prompt, or use a bigger model, before reading anything else.
  downgraded        `met` claimed without a verbatim excerpt. A high count means the model is
                    asserting elements it cannot quote — the validator catches it, but it also
                    tells you the element verdicts are being guessed rather than read.
  rating_vs_elements  proposals whose overall rating disagrees with their own element verdicts.
                    These are caught and downgraded, but the count is a measure of internal
                    inconsistency and belongs in the record.

Nothing here writes to the playbook, the decision log or the state file.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assessor as A  # noqa: E402
import eval_adapters as _ea  # noqa: E402
from assessor import _contract_elements, model_name  # noqa: E402
from pipeline import is_error, propose  # noqa: E402
from playbook import load_controls  # noqa: E402



def corpus_binding(control_ids: list[str]) -> dict:
    """Is each control's corpus still bound to the requirement it was labelled against?

    WB-036: `eval_adapters` has computed this since WB-029 and the EVL controls check it, but
    nothing in the measuring path consulted it. Both corpora were stale — M3.6 labelled against
    a thirteen-element decomposition while the assessor judged against three, with colliding
    ids and different text — and four probe runs reported met/unset counts against those labels
    as though they described the requirement under test. A stale binding does not make the
    mechanism numbers wrong; it makes every comparison to an authored label meaningless.
    """
    try:
        rows = _ea.corpus_case_rows()
    except Exception as e:                          # the probe must still run without the corpus
        return {"available": False, "reason": str(e), "by_control": {}}
    out = {"available": True, "by_control": {}}
    for cid in control_ids:
        rs = [r for r in rows if r.get("control_id") == cid]
        if not rs:
            continue
        out["by_control"][cid] = {
            "cases": len(rs),
            "recorded": next((r.get("requirement_sha") for r in rs if r.get("requirement_sha")), None),
            "live": next((r.get("requirement_sha_live") for r in rs), None),
            "stale": [r["case_id"] for r in rs if r.get("requirement_sha_mismatch")],
            "unbound": [r["case_id"] for r in rs if not r.get("requirement_sha")],
        }
    return out


def print_binding(binding: dict) -> bool:
    """Print the binding state. Returns True when every examined corpus is still bound."""
    if not binding.get("available"):
        print(f"corpus binding: not checked ({binding.get('reason', 'unavailable')})\n")
        return True
    clean = True
    for cid, b in binding["by_control"].items():
        if b["stale"] or b["unbound"]:
            clean = False
            what = "stale" if b["stale"] else "unbound"
            print(f"!! {cid} corpus is {what.upper()} — labels recorded against requirement "
                  f"{b['recorded']}, live requirement is {b['live']}")
            print(f"   affected cases: {', '.join(b['stale'] or b['unbound'])}")
    if not clean:
        print("   The mechanism counts below are still valid — unset, downgraded and met measure\n"
              "   whether the model returns usable verdicts, and do not depend on the labels.\n"
              "   Any comparison to an authored full/partial/none label is NOT TESTABLE until the\n"
              "   labels are re-argued against the current requirement.\n")
    return clean


def load_all_controls(workbook: Path):
    libs = load_controls(str(workbook))
    return [c for v in libs.values() for c in v]


def read_evidence(path: Path) -> list[tuple[str, str]]:
    """Return [(label, text)] from a file or from every text file in a directory."""
    if path.is_file():
        return [(path.name, path.read_text(errors="ignore"))]
    out = []
    for p in sorted(path.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".txt", ".md", ".csv", ".log", ".json"):
            out.append((str(p.relative_to(path)), p.read_text(errors="ignore")))
    return out


def probe_one(control, label: str, text: str, mode: str | None = None) -> dict:
    if mode:
        A.ELEMENT_PASS = mode
    elements = _contract_elements(control)
    ai = propose(control, {"text": text}, None)
    row = {
        "control": control.id, "library": control.lib, "evidence": label,
        "n_elements": len(elements), "error": None, "mode": mode or A.ELEMENT_PASS,
    }
    if is_error(ai):
        row["error"] = ai.get("error", "assessor call failed")
        return row

    verdicts = ai.get("elementVerdicts") or []
    by_status = Counter(v.get("status") for v in verdicts)
    row.update({
        "sufficiency": ai.get("sufficiency"),
        "maturity": ai.get("proposedMaturity"),
        "met": by_status.get("met", 0),
        "not_evidenced": by_status.get("not_evidenced", 0),
        "not_applicable": by_status.get("not_applicable", 0),
        "unset": by_status.get("unset", 0),
        "downgraded": sum(1 for v in verdicts if v.get("downgraded")),
        "flags": ai.get("flags", []),
        "verdicts": [{"element_id": v.get("element_id"), "status": v.get("status"),
                      "has_excerpt": bool(v.get("excerpt")),
                      "rejected_excerpt": v.get("rejected_excerpt")} for v in verdicts],
        # The rejected text, so a downgrade can be diagnosed instead of counted. A paraphrase
        # and a quote that lost its markdown markup produce the same count and need opposite fixes.
        "rejections": [{"element_id": v.get("element_id"), "reason": v.get("downgraded"),
                        "text": v.get("rejected_excerpt")}
                       # `is not None`, not truthiness: an empty rejected excerpt IS the finding —
                       # the model claimed met and offered nothing. Filtering on truthiness hid it.
                       for v in verdicts if v.get("rejected_excerpt") is not None],
    })
    # Internal consistency: does the headline rating follow from the model's own elements?
    decided = [v for v in verdicts if v.get("status") in ("met", "not_evidenced")]
    if decided:
        all_met = all(v["status"] == "met" for v in decided)
        none_met = all(v["status"] == "not_evidenced" for v in decided)
        expected = "full" if all_met else ("none" if none_met else "partial")
        row["elements_imply"] = expected
        row["rating_matches_elements"] = (expected == ai.get("sufficiency"))
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", type=Path, default=None, help="playbook xlsx (default: first in data/)")
    ap.add_argument("--controls", nargs="*", default=["M3.6", "M3.12"], help="control ids to probe")
    ap.add_argument("--evidence", type=Path, default=ROOT / "sample_evidence",
                    help="evidence file or directory")
    ap.add_argument("--json", type=Path, default=None, help="write the full result here")
    ap.add_argument("--mode", choices=["split", "combined", "both"], default="both",
                    help="element-verdict strategy. 'both' runs each and prints the difference, "
                         "which is the only way to tell whether splitting the call actually helped.")
    args = ap.parse_args()

    workbook = args.workbook or next((ROOT / "data").glob("*.xlsx"), None)
    if not workbook:
        print("no workbook found in data/", file=sys.stderr)
        return 2
    if not args.evidence.exists():
        print(f"evidence path not found: {args.evidence}", file=sys.stderr)
        return 2

    controls = {c.id: c for c in load_all_controls(workbook)}
    missing = [cid for cid in args.controls if cid not in controls]
    if missing:
        print(f"not in the workbook: {', '.join(missing)}", file=sys.stderr)
        return 2

    docs = read_evidence(args.evidence)
    if not docs:
        print(f"no evidence documents under {args.evidence}", file=sys.stderr)
        return 2

    binding = corpus_binding(args.controls)
    modes = ["combined", "split"] if args.mode == "both" else [args.mode]
    print(f"model: {model_name()}   controls: {len(args.controls)}   documents: {len(docs)}   "
          f"modes: {', '.join(modes)}\n")
    bound = print_binding(binding)
    rows = []
    for mode in modes:
        if len(modes) > 1:
            print(f"[{mode}]")
        for cid in args.controls:
            c = controls[cid]
            els = _contract_elements(c)
            if not els:
                print(f"{cid}: no contract elements — this control cannot be compared element by element")
            for label, text in docs:
                row = probe_one(c, label, text, mode)
                rows.append(row)
                if row["error"]:
                    print(f"  {cid:8} {label[:34]:36} ERROR  {row['error'][:60]}")
                    continue
                print(f"  {cid:8} {label[:34]:36} {row['sufficiency']:8} "
                      f"met {row['met']} / not-ev {row['not_evidenced']} / n-a {row['not_applicable']} "
                      f"/ unset {row['unset']}   downgraded {row['downgraded']}")

    print("\n--- summary ---")
    per_mode = {}
    for mode in modes:
        scored = [r for r in rows if r["mode"] == mode and not r["error"]]
        failed = len([r for r in rows if r["mode"] == mode and r["error"]])
        total_elements = sum(r["n_elements"] for r in scored)
        total_unset = sum(r["unset"] for r in scored)
        total_met = sum(r["met"] for r in scored)
        rate = (total_unset / total_elements) if total_elements else None
        per_mode[mode] = {"scored": len(scored), "failed": failed, "elements": total_elements,
                          "unset": total_unset, "met": total_met, "unset_rate": rate,
                          "downgraded": sum(r["downgraded"] for r in scored),
                          "inconsistent": len([r for r in scored if r.get("rating_matches_elements") is False])}
        m = per_mode[mode]
        warn = "   ELEMENT VERDICTS ARE NOT BEING RETURNED" if (rate or 0) > 0.25 else ""
        print(f"{mode:9} {m['scored']} scored / {m['failed']} failed   "
              f"unset {m['unset']}/{m['elements']}"
              f"{f' = {rate:.1%}' if rate is not None else ''}{warn}")
        # Zero met across the whole run is its own finding: a model answering "not evidenced"
        # to everything scores well against a corpus that is mostly `none` and is worthless.
        print(f"{'':9} met {m['met']}   downgraded {m['downgraded']}   "
              f"rating_vs_elements {m['inconsistent']}"
              f"{'   NO ELEMENT WAS EVER RATED MET' if m['elements'] and not m['met'] else ''}")

    if len(modes) > 1 and all(per_mode[m]["unset_rate"] is not None for m in modes):
        delta = per_mode["combined"]["unset_rate"] - per_mode["split"]["unset_rate"]
        verdict = ("splitting the call helped" if delta > 0.05 else
                   "splitting the call made it worse" if delta < -0.05 else
                   "no material difference — the split is not the fix here")
        print(f"\nunset_rate combined {per_mode['combined']['unset_rate']:.1%} "
              f"-> split {per_mode['split']['unset_rate']:.1%}   ({verdict})")

    rejected = [(r["control"], r["evidence"], j) for r in rows for j in r.get("rejections", [])]
    if rejected:
        print(f"\n--- {len(rejected)} rejected met-excerpt(s) ---")
        print("Read these before changing anything. A paraphrase is the model's failure; a quote "
              "that merely lost its markdown markup is the verbatim check's.")
        for cid, label, j in rejected[:12]:
            shown = f'"{j["text"][:140]}"' if j.get("text") else "(no excerpt offered at all)"
            print(f'  {cid} {label[:22]:24} {j["element_id"]}: {shown}')

    if not bound:
        print("\nLABEL COMPARISON: NOT TESTABLE — the corpus labels describe a superseded "
              "requirement.\nRe-argue eval/corpus/<control>/LABELS.md against the current "
              "elements and update\nrequirement_sha in elements.yaml before reading these "
              "counts as accuracy.")

    if not [r for r in rows if not r["error"]]:
        print("\nNothing was scored. This is not a pass — check the provider and the model are reachable.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"model": model_name(), "workbook": str(workbook),
                                         "evidence": str(args.evidence), "modes": modes,
                                         "corpus_binding": binding, "label_comparison_testable": bound,
                                         "summary": per_mode, "rows": rows}, indent=1))
        print(f"\nwritten: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
