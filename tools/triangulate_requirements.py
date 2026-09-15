#!/usr/bin/env python3
"""CLI for WB-100 Requirement Triangulation & Element Sufficiency.

WB-102: this entry point used to report `reviewable` (exit 0) on an element set where every
element still sat at `pending_human` with an empty reviewer and an empty rationale, while
`validate_triangulation.py` reported `blocked` (exit 2) on exactly the same inputs, because
only that one loaded the human-decision file.  Two gates that disagree are one gate and one
rubber stamp.  This tool now loads the decisions file too and refuses to call an
undispositioned set reviewable.  Pass --decisions explicitly, or let it resolve the
conventional path; --allow-pending is available for a deliberately exploratory run and is
recorded in the report so it cannot be mistaken for a clean pass.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from governance.triangulation import SourceRegistry, control_sufficiency, build_change_alerts, digest


def load_yaml(p):
    return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True)
    ap.add_argument("--elements", required=True)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--sources", default=str(ROOT / "requirements/triangulation/sources.yaml"))
    ap.add_argument("--as-of", default="2026-09-14")
    ap.add_argument("--decisions", default=None,
                    help="human element-disposition file; defaults to the conventional path "
                         "requirements/triangulation/<CONTROL>_element_decisions.yaml")
    ap.add_argument("--allow-pending", action="store_true",
                    help="report an undispositioned element set without failing (exploratory only)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    elements_doc = load_yaml(args.elements)
    findings_doc = load_yaml(args.findings)
    reg = SourceRegistry.from_yaml(args.sources)
    elements = elements_doc.get("controls", {}).get(args.control, {}).get("elements") or elements_doc.get("elements") or []
    decisions_path = Path(args.decisions) if args.decisions else (
        ROOT / f"requirements/triangulation/{args.control}_element_decisions.yaml")
    human = load_yaml(decisions_path) if decisions_path.exists() else {}
    report = control_sufficiency(elements, findings_doc.get("findings", []), reg,
                                 as_of=args.as_of, control_id=args.control,
                                 human_decisions=human)
    report["source_registry_digest"] = digest(reg.snapshot())
    report["change_alerts"] = build_change_alerts(reg, as_of=args.as_of)

    ctl = report["control"]
    pending = list(ctl.get("human_decision_pending") or [])
    if not decisions_path.exists():
        # No file at all is worse than a file full of pendings: nothing has been asked, so
        # nothing can have been answered.  Say so rather than defaulting to reviewable.
        pending = [str(e.get("id") or e.get("element_id") or "") for e in elements]
        ctl["human_decision_pending"] = pending
        ctl["human_decisions_file"] = None
    else:
        ctl["human_decisions_file"] = str(decisions_path)
    ctl["allow_pending"] = bool(args.allow_pending)
    if pending and not args.allow_pending and ctl.get("status") == "reviewable":
        ctl["status"] = "blocked"
        ctl["blocked_reason"] = (
            f"{len(pending)} element(s) carry no recorded human disposition — a triangulation "
            f"report is not a requirements release")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["control"], indent=2))
    return 0 if report["control"]["status"] == "reviewable" else 2

if __name__ == "__main__":
    raise SystemExit(main())
