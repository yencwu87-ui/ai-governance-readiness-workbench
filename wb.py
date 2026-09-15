#!/usr/bin/env python3
"""WB-043 — the workbench from a terminal.

The full cycle, no browser:

    python wb.py start      M3.6 --evidence ./evidence/validation-report.md
    python wb.py assess     M3.6-a1b2c3d4e5
    python wb.py read       M3.6-a1b2c3d4e5 --sufficiency partial --maturity 3 \\
                            --reason "criteria are approved but no result for the deployed version" \\
                            --element e1=met --element e2=not_evidenced --reviewer "Yen"
    python wb.py compare    M3.6-a1b2c3d4e5
    python wb.py challenge  M3.6-a1b2c3d4e5
    python wb.py decide     M3.6-a1b2c3d4e5 --sufficiency partial --maturity 3 \\
                            --reason "..." --reviewer "Yen"

    python wb.py show M3.6-a1b2c3d4e5
    python wb.py list --open
    python wb.py verify
    python wb.py metrics
    python wb.py migrate data/assessments.json

`read` deliberately requires --reviewer and refuses an empty reason, and `decide` runs the same
reason check the UI runs. A headless path that skipped either would reproduce the hollow decision
record at machine speed, which is worse than not having the path at all.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402
import events  # noqa: E402
import llm  # noqa: E402


def _elements(pairs: list[str] | None) -> list[dict]:
    out = []
    for p in pairs or []:
        if "=" not in p:
            sys.exit(f"--element expects id=status, got {p!r}")
        eid, status = p.split("=", 1)
        out.append({"element_id": eid.strip(), "status": status.strip()})
    return out


def cmd_start(a) -> int:
    text = ""
    if a.evidence:
        p = Path(a.evidence)
        if not p.exists():
            sys.exit(f"evidence not found: {p}")
        text = p.read_text(errors="ignore") if p.is_file() else "\n\n".join(
            f.read_text(errors="ignore") for f in sorted(p.rglob("*")) if f.is_file())
    cid = core.start(a.control, framework=a.framework or "", actor=a.actor)
    core.bind_evidence(cid, {"text": text, "source": str(a.evidence or "(none)")}, actor=a.actor)
    print(cid)
    return 0


def cmd_assess(a) -> int:
    p = core.assess(a.cycle_id)
    print(f"{p.get('sufficiency')} / maturity {p.get('proposedMaturity')}")
    for v in p.get("elementVerdicts") or []:
        print(f"  {v['element_id']:6} {v['status']}")
    if p.get("flags"):
        print("\nvalidator flags:")
        for f in p["flags"]:
            print(f"  - {f}")
    print("\nHidden from the reviewer until a read is recorded.")
    return 0


def cmd_read(a) -> int:
    read = {"sufficiency": a.sufficiency, "maturity": a.maturity, "reason": a.reason,
            "element_verdicts": _elements(a.element)}
    core.record_read(a.cycle_id, read, actor=a.reviewer)
    print(f"recorded: {a.sufficiency} / {a.maturity} by {a.reviewer}")
    prop = core.proposal_for_reviewer(a.cycle_id)
    if prop:
        print(f"assessor proposed: {prop.get('sufficiency')} / {prop.get('proposedMaturity')}")
    return 0


def cmd_compare(a) -> int:
    from compare import headline
    d = core.compare_reads(a.cycle_id)
    print(headline(d))
    for r in d.get("rows") or []:
        mark = ("=" if r["agree"] else "x") if r["compared"] else "."
        print(f"  {mark} {r['element_id']:6} you {r['reviewer']:14} assessor {r['ai']}")
    return 0


def cmd_challenge(a) -> int:
    out = core.challenge(a.cycle_id)
    print(f"{out.get('challenge_outcome')} — scope {', '.join(out.get('scope_elements') or [])}")
    print(f"supports: {out.get('supports_tally')}")
    for c in out.get("challenges") or []:
        print(f"\n  [{c.get('supports')}] {c.get('challenge_strength')} — "
              f"{c.get('requirement_pointer', {}).get('element_id')}")
        print(f"  {c.get('challenge')}")
        if c.get("resolution_pointer"):
            print(f"  settles it: {c['resolution_pointer']}")
    return 0


def cmd_decide(a) -> int:
    d = core.decide(a.cycle_id, sufficiency=a.sufficiency, maturity=a.maturity,
                    reason=a.reason, reviewer=a.reviewer, action=a.action)
    print(f"decided {d['sufficiency']} / {d['maturity']} by {a.reviewer}")
    if d.get("supersedes"):
        print(f"  revised from {d['supersedes']['sufficiency']} / {d['supersedes']['maturity']}")
    return 0


def cmd_show(a) -> int:
    s = core.state(a.cycle_id)
    if not s:
        sys.exit(f"no such cycle: {a.cycle_id}")
    if a.json:
        print(json.dumps(s, indent=1, default=str))
        return 0
    print(f"{s['cycle_id']}  {s['control_id']} ({s.get('framework', '')})  [{s['stage']}]")
    for kind, ts, actor in s["history"]:
        print(f"  {ts}  {kind:16} {actor}")
    return 0


def cmd_list(a) -> int:
    states = core.open_cycles() if a.open else list(events.iter_states())
    for s in states:
        print(f"{s['cycle_id']:32} {s['control_id']:10} {s['stage']}")
    print(f"\n{len(states)} cycle(s)")
    return 0


def cmd_verify(a) -> int:
    r = events.verify()
    print(f"{r['events']} events, chain {'intact' if r['intact'] else 'BROKEN'}")
    for b in r["breaks"]:
        print(f"  index {b['index']}: {b['reason']}")
    return 0 if r["intact"] else 1


def cmd_metrics(a) -> int:
    s = llm.summary()
    print(f"{s['calls']} model call(s)\n")
    print(f"{'role':24} {'calls':>6} {'fail':>6} {'median ms':>10}  models")
    for role, m in sorted(s["by_role"].items()):
        print(f"{role:24} {m['calls']:>6} {m['failures']:>6} {str(m['median_ms']):>10}  "
              f"{', '.join(m['models'])}")
    return 0


def _controls_in_scope(scope: str | None):
    import glob
    from playbook import load_controls
    wb = sorted(glob.glob("data/*.xlsx"))
    if not wb:
        sys.exit("no playbook workbook in data/")
    libs = load_controls(wb[0])
    keys = [k.strip().lower() for k in scope.split(",")] if scope else None
    out = [c for lib, cs in libs.items() for c in cs
           if not keys or any(k in lib.lower() for k in keys)]
    if not out:
        sys.exit(f"no controls in scope {scope!r}")
    return out


def cmd_run(a) -> int:
    import runs as R
    controls = _controls_in_scope(a.scope)
    print(f"taking a run over {len(controls)} control(s) — no model is called, nothing is assessed")
    run = R.take(a.folder, controls, actor=a.actor, trigger=a.trigger, min_ratio=a.min_ratio)
    covered = sum(1 for v in run["evidence"].values() if v["matched"])
    decided = sum(1 for v in run["outcomes"].values() if v)
    print(f"{run['run_id']}   catalog {run['catalog_sha']}")
    print(f"  {run['scan']['documents']} document(s), {run['scan']['passages']} passage(s)")
    print(f"  {covered} of {len(controls)} control(s) have matching evidence")
    print(f"  {decided} carry a recorded decision")
    prev = R.previous(run["run_id"])
    d = None
    if prev:
        import drift as D
        d = D.compare(prev, run)
        print(f"\n{d['changed']} change(s) since {prev['run_id']}")
    else:
        print("\nFirst run — drift needs two runs to compare.")
    import work_queue as Q
    rows = Q.build(run, d)
    print()
    print(Q.render(rows, run=run))
    return 0


def cmd_drift(a) -> int:
    import drift as D
    import runs as R
    all_runs = R.load_all()
    if len(all_runs) < 2:
        sys.exit(f"{len(all_runs)} run(s) recorded — drift needs two")
    after = R.get(a.after) if a.after else all_runs[-1]
    before = R.get(a.before) if a.before else R.previous(after["run_id"])
    if not before or not after:
        sys.exit("run not found")
    d = D.compare(before, after)
    print(D.render(d, show_unchanged=a.all))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(d, indent=1, default=str))
        print(f"\nwritten: {a.json}")
    return 0


def cmd_runs(a) -> int:
    import runs as R
    rows = R.load_all()
    if not rows:
        print("No runs recorded. `wb.py run <evidence-folder>` takes the first one.")
        return 0
    for r in rows:
        covered = sum(1 for v in r["evidence"].values() if v["matched"])
        print(f"{r['run_id']:34} {r['ts']}  catalog {r['catalog_sha']}  "
              f"{covered}/{len(r['catalog'])} covered  ({r['trigger']})")
    return 0


def cmd_queue(a) -> int:
    import runs as R
    import work_queue as Q
    run = R.latest(1)
    run = run[0] if run else None
    d = None
    if run:
        prev = R.previous(run["run_id"])
        if prev:
            import drift as D
            d = D.compare(prev, run)
    elif not a.quiet:
        print("No run recorded yet, so coverage is unknown. `wb.py run <folder>` first for a "
              "fuller queue.\n")
    print(Q.render(Q.build(run, d, limit=a.limit), run=run))
    return 0


def cmd_report(a) -> int:
    import report as R
    d = R.gather(a.control)
    if not d["rows"] and not d["open"]:
        print("No cycles in the event log yet.")
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.markdown or a.out.suffix == ".md":
        a.out.write_text(R.render_markdown(d))
    else:
        R.render_docx(d, a.out)
    print(f"{a.out}  —  {d['counts']['decided']} decision(s), {d['counts']['open']} open, "
          f"chain {'intact' if d['chain']['intact'] else 'BROKEN'}")
    return 0


def cmd_migrate(a) -> int:
    blob = json.loads(Path(a.path).read_text())
    made = events.import_legacy(blob)
    print(f"imported {len(made)} cycle(s) from {a.path}")
    print("Every imported cycle is marked imported=true and actored to `migration` — a record\n"
          "reconstructed from a mutable file is not the same evidence as one written when it\n"
          "happened, and replay can exclude it.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="wb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="open a cycle and bind evidence")
    s.add_argument("control")
    s.add_argument("--evidence", help="file or folder")
    s.add_argument("--framework", default="")
    s.add_argument("--actor", default="system")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("assess", help="run the assessor (result stays hidden)")
    s.add_argument("cycle_id")
    s.set_defaults(fn=cmd_assess)

    s = sub.add_parser("read", help="record the reviewer's own reading")
    s.add_argument("cycle_id")
    s.add_argument("--sufficiency", required=True, choices=["none", "partial", "full"])
    s.add_argument("--maturity", type=int, required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--reviewer", required=True)
    s.add_argument("--element", action="append", metavar="e1=met")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("compare", help="diff the two reads element by element")
    s.add_argument("cycle_id")
    s.set_defaults(fn=cmd_compare)

    s = sub.add_parser("challenge", help="attack the disagreement")
    s.add_argument("cycle_id")
    s.set_defaults(fn=cmd_challenge)

    s = sub.add_parser("decide", help="close the cycle")
    s.add_argument("cycle_id")
    s.add_argument("--sufficiency", required=True, choices=["none", "partial", "full"])
    s.add_argument("--maturity", type=int, required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--reviewer", required=True)
    s.add_argument("--action", default="accept")
    s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("show", help="one cycle")
    s.add_argument("cycle_id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("list", help="all cycles")
    s.add_argument("--open", action="store_true", help="only cycles without a decision")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("verify", help="check the event chain")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("metrics", help="per-role model call metrics")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("report", help="generate the assurance workpaper from the record")
    s.add_argument("--control")
    s.add_argument("--out", type=Path, default=Path("reports/assurance-workpaper.docx"))
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("run", help="take a run — observe the estate, assess nothing")
    s.add_argument("folder")
    s.add_argument("--scope", help="comma-separated library keywords, e.g. MAS,SAFR")
    s.add_argument("--actor", default="system")
    s.add_argument("--trigger", default="manual")
    s.add_argument("--min-ratio", type=float)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("drift", help="what changed between two runs")
    s.add_argument("--before")
    s.add_argument("--after")
    s.add_argument("--all", action="store_true", help="include unchanged controls")
    s.add_argument("--json", type=Path)
    s.set_defaults(fn=cmd_drift)

    s = sub.add_parser("runs", help="list runs")
    s.set_defaults(fn=cmd_runs)

    s = sub.add_parser("queue", help="what to assess next, and why")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("migrate", help="import the legacy assessments.json blob")
    s.add_argument("path")
    s.set_defaults(fn=cmd_migrate)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except core.CycleError as e:
        sys.exit(f"refused: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
