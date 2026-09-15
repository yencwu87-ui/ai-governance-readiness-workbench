"""WB-057 — what to assess next, and why.

The population problem is a sequencing problem. There are 195 controls, reviewer time is the
scarce resource, and the evaluation set that replay will run over is only as good as the reads in
it. Twenty controls clicked through to generate data produce twenty weak labels. Ten read
properly produce ten good ones, and ten good labels beat twenty careless ones by a wide margin.

So this ranks. It never assesses anything and it never decides anything — it answers "where is an
hour of reviewer attention worth most right now", and the run report answers it the same way
Puppet's does: by what changed.

Ranking, highest first:

  1  drift          the estate moved under an unchanged requirement — a previously adequate
                    control may no longer be, which is the only finding that is actively decaying
  2  evidence lost  a control that had evidence and now has none. More urgent than one that never
                    had any, because something was withdrawn or moved
  3  stale decision the requirement changed since the decision was recorded, so the recorded
                    outcome answers a different question and is not a conclusion any more
  4  new evidence   evidence appeared for a control that had none
  5  never assessed  has evidence, has never been read. The bulk of a first pass
  6  error          the assessor failed and nothing was recorded

Unchanged, decided controls with unchanged evidence are not listed. On a healthy estate most of
the library should be absent from this queue, and that absence is the point rather than an
oversight.
"""
from __future__ import annotations

from typing import Any

import events

REASONS = ("drift", "evidence_lost", "stale_decision", "new_evidence", "never_assessed", "error")

_PRIORITY = {r: i for i, r in enumerate(REASONS)}

_WHY = {
    "drift": "evidence changed since the last run under an unchanged requirement",
    "evidence_lost": "had matching evidence at the last run and has none now",
    "stale_decision": "the requirement changed after the decision was recorded",
    "new_evidence": "evidence appeared for a control that previously had none",
    "never_assessed": "has evidence and no reviewer reading has ever been recorded",
    "error": "the last assessor call failed and nothing was recorded",
}


def _latest_decision_by_control() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in events.iter_states():
        cid = s.get("control_id")
        if not cid or s.get("stage") != "decided":
            continue
        prev = out.get(cid)
        if prev is None or s["updated"] > prev["updated"]:
            out[cid] = s
    return out


def build(run: dict | None = None, diff: dict | None = None, *,
          limit: int = 0) -> list[dict[str, Any]]:
    """Rank the controls worth a reviewer's time.

    `run` supplies current evidence coverage and the catalog. `diff` supplies what moved since
    the previous run. Either may be absent — with neither, this degrades to "controls with
    evidence and no reading", which is the correct first-pass answer on an empty event log.
    """
    decided = _latest_decision_by_control()
    rows: dict[str, dict] = {}

    def mark(cid: str, reason: str, note: str = "", framework: str = "") -> None:
        row = rows.setdefault(cid, {"control_id": cid, "framework": framework,
                                    "reasons": [], "notes": []})
        if framework and not row["framework"]:
            row["framework"] = framework
        if reason not in row["reasons"]:
            row["reasons"].append(reason)
        if note:
            row["notes"].append(note)

    if diff:
        for r in diff.get("rows") or []:
            cid, fw = r["control_id"], r.get("framework", "")
            if "evidence_changed" in r["classes"]:
                mark(cid, "drift", r["notes"][0] if r["notes"] else "", fw)
            if "evidence_lost" in r["classes"]:
                mark(cid, "evidence_lost", "", fw)
            if "newly_covered" in r["classes"]:
                mark(cid, "new_evidence", "", fw)
            if "requirement_changed" in r["classes"] and cid in decided:
                mark(cid, "stale_decision",
                     "the earlier outcome answers a different question", fw)

    if run:
        cat = {e["control_id"]: e for e in run.get("catalog") or []}
        for cid, ev in (run.get("evidence") or {}).items():
            fw = (cat.get(cid) or {}).get("framework", "")
            if not ev.get("matched"):
                continue
            if cid not in decided:
                mark(cid, "never_assessed", f"{ev['matched']} matching passage(s)", fw)

    for s in events.iter_states():
        cid = s.get("control_id")
        prop = s.get("proposal") or {}
        if cid and prop.get("model") == "error" and s.get("stage") != "decided":
            mark(cid, "error", str(prop.get("error", ""))[:80], s.get("framework", ""))

    out = []
    for cid, row in rows.items():
        row["priority"] = min(_PRIORITY.get(r, 99) for r in row["reasons"])
        row["top_reason"] = REASONS[row["priority"]]
        row["why"] = _WHY[row["top_reason"]]
        row["decided_before"] = cid in decided
        out.append(row)
    out.sort(key=lambda r: (r["priority"], r["control_id"]))
    return out[:limit] if limit else out


def render(rows: list[dict], *, run: dict | None = None) -> str:
    if not rows:
        return ("Nothing is queued. Every control with evidence carries a reading, nothing moved "
                "since\nthe last run, and no assessment is in error. On a healthy estate this is "
                "the expected\nresult of a run, not a failure to look.")
    lines = [f"{len(rows)} control(s) worth a reviewer's time, most urgent first.", ""]
    current = None
    for r in rows:
        if r["top_reason"] != current:
            current = r["top_reason"]
            lines.append(f"## {current.replace('_', ' ')} — {_WHY[current]}")
        note = f"  {r['notes'][0]}" if r["notes"] else ""
        lines.append(f"  {r['control_id']:12} "
                     f"{r['framework'].replace('Control Library - ', ''):14}{note}")
    lines += ["", "Assess these in the app. Each completed cycle becomes a replay case, so the "
                  "reading\nquality here is the quality of every measurement made afterwards — "
                  "ten read properly\nare worth more than twenty clicked through."]
    return "\n".join(lines)
