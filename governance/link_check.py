#!/usr/bin/env python3
"""Check that every cross-reference in the governance artefacts resolves.

The workbench now spans several files that reference each other by id, and none of those
references are checked anywhere. A stale ref does not raise — it silently produces nothing,
which is the failure mode that made data/assessments.json worthless and that WB-021 fixed in
the scanner. This is the same class of problem one layer up.

What it checks:

  play_refs        requirements/mas.yaml tests -> Playbooks & Runbooks sheet
                   controls/*.yaml packs       -> Playbooks & Runbooks sheet
  framework_refs   controls/*.yaml MAS-AIRG-*  -> the MAS control library
  policy_refs      controls/*.yaml             -> keys in policy/ai-lifecycle.yaml
  severity         requirements/mas.yaml       -> the vocabulary the gates use
  lane_b_packs     requirements/mas.yaml       -> recomputed from framework_refs (drift)
  coverage         which MAS controls have no Lane B pack at all

Usage, from repo/:
    python governance/link_check.py            # report
    python governance/link_check.py --fix      # rewrite stale lane_b_packs in place
    python governance/link_check.py --json     # machine-readable

Exit code 1 if any reference fails to resolve. Coverage gaps are reported, not failed —
an uncovered control is a state of the programme, not a broken link.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements" / "mas.yaml"
POLICY = ROOT / "policy" / "ai-lifecycle.yaml"
PACKS = ROOT / "controls"
WORKBOOK = ROOT / "data" / "AI_Governance_Playbook_MGF_SAFR_v0.5.1_contracts.xlsx"
SEVERITIES = {"critical", "high", "medium", "low"}


def play_steps(workbook: Path) -> set[str]:
    """Valid step ids, in plays.py format P<play>.<step>."""
    from openpyxl import load_workbook
    import warnings
    warnings.filterwarnings("ignore")
    ws = load_workbook(workbook, data_only=True)["Playbooks & Runbooks"]
    out, play = set(), None
    for r in range(5, ws.max_row + 1):
        a = str(ws.cell(r, 1).value or "").strip()
        if a.upper().startswith("PLAY"):
            m = re.match(r"PLAY\s+(\d+)", a.upper())
            play = m.group(1) if m else None
        elif play and a.lower().startswith("step"):
            m = re.match(r"step\s+(\d+)", a.lower())
            if m:
                out.add(f"P{play}.{m.group(1)}")
    return out


def mas_control_ids(workbook: Path) -> set[str]:
    from openpyxl import load_workbook
    import warnings
    warnings.filterwarnings("ignore")
    ws = load_workbook(workbook, data_only=True)["Control Library - MAS"]
    h = {str(c.value).strip(): c.column for c in ws[3] if c.value}
    return {str(ws.cell(r, h["MAS ref"]).value).strip()
            for r in range(4, ws.max_row + 1) if ws.cell(r, h["MAS ref"]).value}


def packs() -> dict[str, dict]:
    """Parsed just enough: id -> {file, play_refs, framework_refs, policy_refs, severity}."""
    out = {}
    for f in sorted(glob.glob(str(PACKS / "*.y*ml"))):
        for blk in re.split(r"\n- id: ", Path(f).read_text())[1:]:
            cid = blk.split()[0]
            lst = lambda k: [x.strip() for x in (re.search(rf"{k}: \[(.*?)\]", blk) or
                                                 re.match("", "")).group(1).split(",")] \
                if re.search(rf"{k}: \[(.*?)\]", blk) else []
            sev = re.search(r"\n  severity: (\w+)", blk)
            out[cid] = {"file": Path(f).name, "play_refs": lst("play_refs"),
                        "framework_refs": lst("framework_refs"),
                        "policy_refs": lst("policy_refs"),
                        "severity": sev.group(1) if sev else None}
    return out


def policy_keys(path: Path) -> set[str]:
    import yaml
    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                key = f"{prefix}.{k}" if prefix else k
                yield key
                yield from walk(v, key)
    doc = yaml.safe_load(path.read_text())
    keys = set(walk(doc))
    # policy_refs are written relative to golden_state as well as absolute
    return keys | {k.split("golden_state.", 1)[1] for k in keys if k.startswith("golden_state.")}


def run() -> dict:
    import yaml
    req = yaml.safe_load(REQ.read_text())
    steps, mas_ids, pk, pkeys = play_steps(WORKBOOK), mas_control_ids(WORKBOOK), packs(), policy_keys(POLICY)

    errors, warnings_ = [], []
    tc = req.get("test_controls") or {}

    # requirements -> plays
    for cid, e in tc.items():
        for r in (e.get("tests", {}).get("play_refs") or []):
            if r not in steps:
                errors.append(f"requirements/mas.yaml {cid}: play_ref {r} not in the playbook")
        sev = e.get("severity")
        if sev not in SEVERITIES:
            errors.append(f"requirements/mas.yaml {cid}: severity {sev!r} not in {sorted(SEVERITIES)}")
        mode = e.get("assurance_mode")
        if mode is not None and mode not in {"lane_a", "lane_b", "hybrid", "human_only"}:
            errors.append(f"requirements/mas.yaml {cid}: invalid assurance_mode {mode!r}")
        if sev == "critical" and mode is None:
            errors.append(f"requirements/mas.yaml {cid}: critical control needs an explicit assurance_mode")
        elif sev == "critical" and mode == "lane_b" and not e.get("lane_b_packs"):
            errors.append(f"requirements/mas.yaml {cid}: critical lane_b assurance has no Lane-B pack")
        elif sev == "critical" and mode == "human_only" and e.get("lane_b_packs"):
            errors.append(f"requirements/mas.yaml {cid}: critical human_only assurance declares Lane-B pack(s)")
        if cid not in mas_ids:
            errors.append(f"requirements/mas.yaml {cid}: not a control in the MAS library")

    # requirement text must name a control that exists
    for cid in (req.get("controls") or {}):
        if cid not in mas_ids:
            errors.append(f"requirements/mas.yaml controls.{cid}: not in the MAS library")

    # packs -> plays, MAS library, policy
    for cid, p in pk.items():
        for r in p["play_refs"]:
            if r and r not in steps:
                errors.append(f"{p['file']} {cid}: play_ref {r} not in the playbook")
        for fr in p["framework_refs"]:
            m = re.match(r"MAS-AIRG-([MF][\d.]+)$", fr)
            if m and m.group(1) not in mas_ids:
                errors.append(f"{p['file']} {cid}: framework_ref {fr} not in the MAS library")
        for pr in p["policy_refs"]:
            if pr and pr not in pkeys:
                errors.append(f"{p['file']} {cid}: policy_ref {pr} not a key in ai-lifecycle.yaml")

    # lane_b_packs drift
    actual = defaultdict(list)
    for cid, p in pk.items():
        for fr in p["framework_refs"]:
            m = re.match(r"MAS-AIRG-([MF][\d.]+)$", fr)
            if m:
                actual[m.group(1)].append(cid)
    drift = {}
    for cid, e in tc.items():
        want, have = sorted(actual.get(cid, [])), sorted(e.get("lane_b_packs") or [])
        if want != have:
            drift[cid] = {"declared": have, "actual": want}
            warnings_.append(f"{cid}: lane_b_packs stale — declared {have}, actual {want}")

    uncovered = sorted(c for c in tc if not actual.get(c))
    crit_uncovered = sorted(c for c in uncovered if tc[c].get("severity") == "critical")

    return {"errors": errors, "warnings": warnings_, "drift": drift,
            "counts": {"mas_controls": len(mas_ids), "with_tests": len(tc),
                       "play_steps": len(steps), "packs": len(pk),
                       "lane_b_covered": len(actual), "uncovered": len(uncovered)},
            "uncovered": uncovered, "critical_uncovered": crit_uncovered}


def fix_drift(drift: dict) -> int:
    """Rewrite lane_b_packs to the computed value. Only touches that one line per control."""
    if not drift:
        return 0
    text, n = REQ.read_text(), 0
    for cid, d in drift.items():
        pat = re.compile(rf"(\n  {re.escape(cid)}:\n(?:.*\n)*?    lane_b_packs: )\[[^\]]*\]")
        new = f"[{', '.join(d['actual'])}]"
        text, k = pat.subn(lambda m: m.group(1) + new, text, count=1)
        n += k
    REQ.write_text(text)
    return n


def report(r: dict) -> None:
    c = r["counts"]
    print(f"MAS controls {c['mas_controls']}   with tests {c['with_tests']}   "
          f"play steps {c['play_steps']}   Lane B packs {c['packs']}")
    print(f"Lane B coverage: {c['lane_b_covered']} of {c['with_tests']} controls\n")
    for e in r["errors"]:
        print("ERROR  ", e)
    for w in r["warnings"]:
        print("DRIFT  ", w)
    if not r["errors"] and not r["warnings"]:
        print("all references resolve, no drift")
    print(f"\nNo Lane B pack ({len(r['uncovered'])}): {', '.join(r['uncovered'])}")
    if r["critical_uncovered"]:
        print(f"\nOf those, severity CRITICAL and untested by any pack:")
        for cid in r["critical_uncovered"]:
            print(f"  {cid}")
        print("  These controls have no Lane-B machine verdict. v0.4 requires their assurance_mode")
        print("  to be explicit (currently human_only); non-waivable policy therefore remains a named")
        print("  human/document assurance path until a machine-testable pack is approved.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix", action="store_true", help="rewrite stale lane_b_packs in place")
    a = ap.parse_args()
    res = run()
    if a.fix:
        n = fix_drift(res["drift"])
        print(f"rewrote lane_b_packs for {n} control(s)")
        res = run()
    print(json.dumps(res, indent=2)) if a.json else report(res)
    sys.exit(1 if res["errors"] else 0)
