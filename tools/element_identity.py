#!/usr/bin/env python3
"""WB-104 — show element identity, and which labels survive a contract revision.

    python tools/element_identity.py --elements eval/corpus/M3.6/elements.yaml
    python tools/element_identity.py --old <prior.yaml> --new eval/corpus/M3.6/elements.yaml

With `--old`, nothing is written. The carry decision is reported and a person applies it; an
exact match is stated as decidable, a near match is stated as pending. Writing labels back
automatically would make this tool the thing that decides what an obligation means.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.element_identity import diff_contracts, duplicate_obligations, identify


def load(path: str) -> list[dict]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if isinstance(doc, dict):
        for key in ("elements",):
            if doc.get(key):
                return doc[key]
        for block in (doc.get("controls") or {}).values():
            if isinstance(block, dict) and block.get("elements"):
                return block["elements"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elements", help="a single contract to list identities for")
    ap.add_argument("--old", help="the prior contract, with its labels")
    ap.add_argument("--new", help="the current contract")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.elements and not (a.old or a.new):
        rows = identify(load(a.elements))
        dupes = duplicate_obligations(load(a.elements))
        if a.json:
            print(json.dumps({"elements": rows, "duplicate_obligations": dupes}, indent=2))
            return 0
        print(f"{len(rows)} element(s)\n")
        for r in rows:
            print(f"  {str(r.get('id')):5} {r['uid']}  {r['slug']}")
            print(f"        {r['text'][:150]}")
        if dupes:
            print(f"\n  {len(dupes)} obligation(s) appear under more than one id:")
            for d in dupes:
                print(f"      {d['uid']}  {', '.join(d['ids'])}  {d['slug']}")
        return 0

    if not (a.old and a.new):
        ap.error("give --elements, or both --old and --new")

    report = diff_contracts(load(a.old), load(a.new))
    if a.json:
        print(json.dumps(report, indent=2))
        return 0

    s = report["summary"]
    print(f"{report['old_count']} element(s) -> {report['new_count']} element(s)\n")
    print(f"  carried automatically      {s['carried']:3}   identical obligation, label travels")
    print(f"  proposed for a person      {s['proposed_for_human']:3}   similar, not identical")
    print(f"  need fresh labels          {s['needs_fresh_labels']:3}")
    print(f"  retired                    {s['retired']:3}   stored judgements now orphaned")

    if report["carried"]:
        print("\n  CARRIED")
        for c in report["carried"]:
            print(f"      {c['old_id']} -> {c['new_id']}  {c['slug']}  labels={c['labels']}")
    if report["proposed"]:
        print("\n  PROPOSED — not applied, decide each one")
        for p in report["proposed"]:
            print(f"      {p['old_id']} -> {p['new_id']}  similarity {p['similarity']}  "
                  f"labels={p['old_labels']}")
            print(f"          was: {p['old_text'][:130]}")
            print(f"          now: {p['new_text'][:130]}")
    if report["new"]:
        print("\n  NEW — no prior obligation resembles these")
        for n in report["new"]:
            print(f"      {n['new_id']}  {n['slug']}  (closest prior {n['closest']})")
    if report["retired"]:
        print("\n  RETIRED — any label or decision stored against these is now orphaned")
        for r in report["retired"]:
            print(f"      {r['old_id']}  {r['slug']}  labels={r['labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
