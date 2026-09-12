"""WB-030 — element-level comparison of the reviewer's blind read and the assessor's proposal.

Deterministic. No model call, no network, no state. `compare()` is a pure function of its
three arguments, so it is unit-testable and its output can be stored in the decision record
as a fact rather than as an opinion.

Why this exists
---------------
Before WB-030 the two sides met only as two words — "partial" against "full" — and the app
said so in a single caption. Rating agreement over three values is a weak signal: an assessor
that reaches the right rating for the wrong reasons is indistinguishable from one that reasons
correctly, and a reviewer who agrees on the rating while disagreeing on every element is
recorded as agreeing. Since v0.5.1 both sides are anchored to the same canonical control
contract, so the comparison can be made where the reasoning actually lives.

Three rules the code enforces, each of which exists because the obvious alternative is wrong:

  1. Silence is never agreement. An element neither side addressed is `unset` on that side and
     is excluded from the compared population. It is reported, not counted.
  2. A failed assessor call is NOT_COMPARABLE, not a disagreement and not an agreement. A run
     that did not happen must never look like a run that found nothing.
  3. The agreement rate has an evidence floor. Below `min_compared` elements the rate is None
     and `floor_met` is False — a rate computed over one element is not a rate.
"""
from __future__ import annotations

import hashlib
import json

#: Verdict a side may hold on one element.
STATUSES = ("met", "not_evidenced", "not_applicable", "unset")

#: Below this many comparable elements, an agreement rate is not reported.
MIN_COMPARED = 3


def _norm_status(v: object) -> str:
    s = str(v or "unset").strip().lower().replace(" ", "_").replace("-", "_")
    if s in ("not_evidenced", "notevidenced", "absent", "missing", "no"):
        return "not_evidenced"
    if s in ("met", "yes", "evidenced", "satisfied"):
        return "met"
    if s in ("not_applicable", "na", "n_a", "notapplicable"):
        return "not_applicable"
    return "unset"


def elements_for(control) -> list[dict]:
    """Lane-A elements of the canonical contract, in contract order.

    Lane-B elements are excluded deliberately: they are evidenced deterministically by the
    control packs, so asking a reviewer or a document assessor to hold an opinion on them
    invites a judgement where a test already exists.
    """
    cid = control.get("id") if isinstance(control, dict) else getattr(control, "id", "")
    lib = control.get("lib") if isinstance(control, dict) else getattr(control, "lib", "")
    try:
        from governance.control_contract import requirement_context
        ctx = requirement_context(cid, lib) or {}
    except Exception:
        return []
    out = []
    for i, e in enumerate(ctx.get("elements") or []):
        if not isinstance(e, dict) or not str(e.get("text") or "").strip():
            continue
        if e.get("lane", "a") == "b":
            continue
        out.append({
            "id": str(e.get("id") or f"e{i}"),
            "text": " ".join(str(e["text"]).split()),
            "scope": str(e.get("scope", "model")),
            "locator": e.get("locator") or f"controls.{cid}.elements[{i}]",
        })
    return out


def _verdict_map(side: dict, key: str, ids: list[str]) -> dict:
    """Pull {element_id: status} from one side, keeping only ids the contract declares."""
    raw = (side or {}).get(key) or []
    if isinstance(raw, dict):                      # {"e1": "met", ...}
        items = [{"element_id": k, "status": v} for k, v in raw.items()]
    else:
        items = [x for x in raw if isinstance(x, dict)]
    known = set(ids)
    out = {}
    for x in items:
        eid = str(x.get("element_id") or x.get("id") or "").strip()
        if eid in known:
            out[eid] = _norm_status(x.get("status"))
    return out


def _excerpts(side: dict, key: str) -> dict:
    raw = (side or {}).get(key) or []
    if not isinstance(raw, list):
        return {}
    return {str(x.get("element_id") or ""): str(x.get("excerpt") or "").strip()
            for x in raw if isinstance(x, dict)}


def _direction(reviewer: str, ai: str) -> str:
    if reviewer == ai:
        return "agree"
    if "not_applicable" in (reviewer, ai):
        return "scope"
    if reviewer == "met" and ai == "not_evidenced":
        return "reviewer_more_generous"
    if ai == "met" and reviewer == "not_evidenced":
        return "assessor_more_generous"
    return "differs"


def _sha(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def is_error(ai: dict | None) -> bool:
    """True when the proposal is an error record or carries no rating at all."""
    if not ai:
        return True
    if ai.get("status") == "error" or ai.get("error"):
        return True
    return not ai.get("sufficiency")


def compare(blind: dict, ai: dict | None, control, min_compared: int = MIN_COMPARED) -> dict:
    """Diff the reviewer's read against the assessor's proposal, element by element.

    blind: the reviewer's own reading — sufficiency, maturity, reason, element_verdicts
    ai:    the assessor proposal — sufficiency, proposedMaturity, elementVerdicts
    """
    elements = elements_for(control)
    ids = [e["id"] for e in elements]
    cid = control.get("id") if isinstance(control, dict) else getattr(control, "id", "")

    if not blind:
        return {"comparable": False, "reason": "no reviewer reading has been recorded",
                "control_id": cid, "rows": [], "disagreements": [],
                "summary": {"n_elements": len(ids)}}
    if is_error(ai):
        return {"comparable": False,
                "reason": "the assessor call did not produce a rating — there is nothing to compare, "
                          "and a failed run must not be recorded as agreement",
                "control_id": cid, "rows": [], "disagreements": [],
                "rating": {"reviewer": blind.get("sufficiency"), "ai": None, "agree": None},
                "summary": {"n_elements": len(ids)}}

    rv = _verdict_map(blind, "element_verdicts", ids)
    av = _verdict_map(ai, "elementVerdicts", ids)
    ax = _excerpts(ai, "elementVerdicts")

    rows, disagreements = [], []
    n_agree = n_compared = r_unset = a_unset = 0
    for e in elements:
        r = rv.get(e["id"], "unset")
        a = av.get(e["id"], "unset")
        r_unset += r == "unset"
        a_unset += a == "unset"
        compared = r != "unset" and a != "unset"
        agree = compared and r == a
        if compared:
            n_compared += 1
            n_agree += agree
            if not agree:
                disagreements.append(e["id"])
        rows.append({
            "element_id": e["id"], "text": e["text"], "scope": e["scope"], "locator": e["locator"],
            "reviewer": r, "ai": a, "compared": compared, "agree": agree if compared else None,
            "direction": _direction(r, a) if compared else "not_compared",
            "ai_excerpt": ax.get(e["id"], ""),
        })

    rating_r = blind.get("sufficiency")
    rating_a = ai.get("sufficiency")
    mat_r, mat_a = blind.get("maturity"), ai.get("proposedMaturity")
    floor_met = n_compared >= min_compared

    return {
        "comparable": True,
        "control_id": cid,
        "schema": "wb030.compare.1",
        "rating": {"reviewer": rating_r, "ai": rating_a, "agree": rating_r == rating_a},
        "maturity": {"reviewer": mat_r, "ai": mat_a, "agree": mat_r == mat_a},
        "rows": rows,
        "disagreements": disagreements,
        "summary": {
            "n_elements": len(ids),
            "n_compared": n_compared,
            "n_agree": n_agree,
            "n_disagree": len(disagreements),
            "reviewer_unset": r_unset,
            "assessor_unset": a_unset,
            # None, not zero: a rate over fewer than min_compared elements is not a measurement.
            "agreement_rate": round(n_agree / n_compared, 3) if (n_compared and floor_met) else None,
            "floor_met": floor_met,
            "min_compared": min_compared,
        },
        "diff_sha": _sha({"c": cid, "r": rv, "a": av}),
    }


def headline(diff: dict) -> str:
    """One line for the UI and the report. Never asserts who is right."""
    if not diff.get("comparable"):
        return f"Not comparable — {diff.get('reason', 'unknown reason')}."
    s = diff["summary"]
    rat = diff["rating"]
    lead = ("Same rating" if rat["agree"] else f"Reviewer {rat['reviewer']} against assessor {rat['ai']}")
    if not s["n_compared"]:
        return f"{lead}. No element was decided on both sides, so nothing was compared."
    tail = f"{s['n_agree']} of {s['n_compared']} elements agree"
    if s["n_disagree"]:
        tail += f", {s['n_disagree']} disagree ({', '.join(diff['disagreements'])})"
    if not s["floor_met"]:
        tail += f" — below the floor of {s['min_compared']}, so no agreement rate is reported"
    return f"{lead}. {tail}."
