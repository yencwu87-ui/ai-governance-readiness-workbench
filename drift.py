"""WB-051 — drift.

Puppet's value is not that it knows the desired state. It is that every thirty minutes it tells
you where reality has moved away from it. This module is that, for controls.

The design constraint that makes continuous audit tractable is silence. A nightly run over 195
controls that reported all 195 would generate more findings per week than a second-line team can
decide on, and the backlog would become the product. So a control whose evidence, yardstick and
outcome are all unchanged produces nothing at all. On a healthy estate most of a run is silent,
and that is the intended result rather than a sign the run did nothing.

The classifications exist to keep three questions apart that look identical in a naive diff:

  the estate moved      evidence changed under an unchanged requirement — the control may no
                        longer hold, and it needs re-assessment
  the yardstick moved   the requirement or the contract changed — the previous outcome is not
                        wrong, it is answering a different question. Outcome comparison is
                        refused for that control, the same rule the corpus binding gate applies.
  coverage moved        a control gained or lost evidence entirely. Evidence lost is a finding,
                        not a silence: a control that had evidence last week and has none now is
                        a more urgent fact than one that never had any.

An unassessed control and a control assessed as `none` are never collapsed. That collapse is how
a coverage gap gets reported as an adverse finding, or an adverse finding as a coverage gap.
"""
from __future__ import annotations

from typing import Iterable

#: Ordered by how much attention each deserves. `unchanged` is last and is never reported.
CLASSES = (
    "evidence_lost",          # had evidence, has none — coverage regressed
    "requirement_changed",    # the yardstick moved; the prior outcome answers a different question
    "evidence_changed",       # the estate moved under an unchanged requirement
    "newly_covered",          # evidence appeared for a control that had none
    "control_added",          # in scope now, was not before
    "control_removed",        # was in scope, is not now
    "outcome_changed",        # a new decision was recorded between the runs
    "unchanged",              # reported nowhere, counted only
)

#: Classes that mean "a model and a human should look at this again".
NEEDS_REASSESSMENT = ("evidence_lost", "requirement_changed", "evidence_changed",
                      "newly_covered", "control_added")

_RATING_ORDER = {"none": 0, "partial": 1, "full": 2}


def _by_id(run: dict, field: str) -> dict:
    if field == "catalog":
        return {e["control_id"]: e for e in run.get("catalog") or []}
    return run.get(field) or {}


def _outcome_direction(before: dict | None, after: dict | None) -> str | None:
    if not before or not after:
        return None
    b, a = _RATING_ORDER.get(before.get("sufficiency")), _RATING_ORDER.get(after.get("sufficiency"))
    if b is None or a is None or a == b:
        return None
    return "improved" if a > b else "regressed"


def compare(before: dict, after: dict) -> dict:
    """Classify every control across two runs. Pure — no model, no I/O."""
    cat_b, cat_a = _by_id(before, "catalog"), _by_id(after, "catalog")
    ev_b, ev_a = _by_id(before, "evidence"), _by_id(after, "evidence")
    out_b, out_a = _by_id(before, "outcomes"), _by_id(after, "outcomes")

    rows = []
    for cid in sorted(set(cat_b) | set(cat_a)):
        row = {"control_id": cid,
               "framework": (cat_a.get(cid) or cat_b.get(cid) or {}).get("framework", ""),
               "classes": [], "notes": []}

        in_b, in_a = cid in cat_b, cid in cat_a
        if in_a and not in_b:
            row["classes"].append("control_added")
        elif in_b and not in_a:
            row["classes"].append("control_removed")

        # --- the yardstick, checked first: it changes how everything else should be read
        if in_a and in_b:
            rb, ra = cat_b[cid].get("requirement_sha"), cat_a[cid].get("requirement_sha")
            cb, ca = cat_b[cid].get("contract_sha"), cat_a[cid].get("contract_sha")
            if (rb and ra and rb != ra) or (cb and ca and cb != ca):
                row["classes"].append("requirement_changed")
                row["notes"].append("the requirement or contract changed between these runs, so "
                                    "the earlier outcome answers a different question — it is "
                                    "not evidence that the control regressed")

        # --- coverage and the estate
        eb, ea = ev_b.get(cid) or {}, ev_a.get(cid) or {}
        had, has = bool(eb.get("matched")), bool(ea.get("matched"))
        if had and not has:
            row["classes"].append("evidence_lost")
            row["notes"].append(f"matched {eb.get('matched')} passage(s) previously and none now")
        elif has and not had:
            row["classes"].append("newly_covered")
        elif had and has and eb.get("digest") != ea.get("digest"):
            row["classes"].append("evidence_changed")
            gained = sorted(set(ea.get("sources") or []) - set(eb.get("sources") or []))
            lost = sorted(set(eb.get("sources") or []) - set(ea.get("sources") or []))
            if gained:
                row["notes"].append(f"new source(s): {', '.join(gained[:4])}")
            if lost:
                row["notes"].append(f"source(s) no longer matching: {', '.join(lost[:4])}")
            if not gained and not lost:
                row["notes"].append("same source(s), changed content")

        # --- the outcome. Recorded, but never attributed to the estate when the yardstick moved.
        ob, oa = out_b.get(cid), out_a.get(cid)
        if (ob or {}).get("cycle_id") != (oa or {}).get("cycle_id"):
            if oa and not ob:
                row["classes"].append("outcome_changed")
                row["notes"].append(f"first decision recorded: {oa.get('sufficiency')} "
                                    f"by {oa.get('reviewer')}")
            elif oa and ob:
                row["classes"].append("outcome_changed")
                d = _outcome_direction(ob, oa)
                row["notes"].append(
                    f"decision moved {ob.get('sufficiency')} -> {oa.get('sufficiency')}"
                    + (f" ({d})" if d else "")
                    + (" — but the requirement also changed, so this is not a comparison of like "
                       "with like" if "requirement_changed" in row["classes"] else ""))
        row["outcome"] = {"before": ob, "after": oa}
        row["outcome_direction"] = (None if "requirement_changed" in row["classes"]
                                    else _outcome_direction(ob, oa))

        if not row["classes"]:
            row["classes"].append("unchanged")
        row["needs_reassessment"] = any(c in NEEDS_REASSESSMENT for c in row["classes"])
        rows.append(row)

    changed = [r for r in rows if r["classes"] != ["unchanged"]]
    counts = {c: sum(c in r["classes"] for r in rows) for c in CLASSES}
    return {
        "before": before["run_id"], "after": after["run_id"],
        "before_ts": before.get("ts"), "after_ts": after.get("ts"),
        "catalog_changed": before.get("catalog_sha") != after.get("catalog_sha"),
        "controls": len(rows), "changed": len(changed),
        "silent": len(rows) - len(changed),
        "counts": counts,
        "rows": rows,
        "attention": [r for r in rows if r["needs_reassessment"]],
    }


def reassessment_queue(diff: dict) -> list[str]:
    """The controls a run should hand to an assessor. Ordered by class priority."""
    order = {c: i for i, c in enumerate(CLASSES)}
    return [r["control_id"] for r in sorted(
        diff["attention"], key=lambda r: min(order.get(c, 99) for c in r["classes"]))]


def render(diff: dict, *, show_unchanged: bool = False) -> str:
    """The run report. Changes only, unless asked otherwise."""
    out = [f"drift  {diff['before']} -> {diff['after']}",
           f"       {diff.get('before_ts')} -> {diff.get('after_ts')}", ""]
    if diff["catalog_changed"]:
        out += ["The compiled catalog changed between these runs. Controls marked "
                "requirement_changed are\nnot comparable on outcome — the yardstick moved, not "
                "necessarily the estate.", ""]
    out.append(f"{diff['controls']} control(s): {diff['changed']} changed, "
               f"{diff['silent']} unchanged and not reported.")
    if not diff["changed"]:
        out += ["", "Nothing moved. On a healthy estate this is the expected result of a run, "
                    "not a failure to look."]
        return "\n".join(out)

    out.append("")
    for cls in CLASSES:
        if cls == "unchanged" and not show_unchanged:
            continue
        rows = [r for r in diff["rows"] if cls in r["classes"]]
        if not rows:
            continue
        out.append(f"## {cls.replace('_', ' ')}  ({len(rows)})")
        for r in rows:
            line = f"  {r['control_id']:12} {r['framework'].replace('Control Library - ', ''):14}"
            if r["notes"]:
                line += r["notes"][0]
            out.append(line)
            for n in r["notes"][1:]:
                out.append(f"  {'':27}{n}")
        out.append("")

    q = reassessment_queue(diff)
    if q:
        out += [f"Hand to an assessor ({len(q)}): {', '.join(q[:20])}"
                + (" …" if len(q) > 20 else ""), ""]
    out.append("This tool observes and does not remediate. Nothing above has been changed for you.")
    return "\n".join(out)
