"""v0.8 Governance Decision Engine.

The engine is deterministic. Models may produce evidence, claims, challenges and falsification
probes, but they do not set the governance outcome. This module compiles the governed record
into a decision posture, consistency checks, escalation signals and a machine-readable basis.

Human reviewers remain the authority: ``evaluate`` produces an eligibility/recommendation
projection; ``enforce`` prevents a decision from silently violating hard governance invariants.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

SUFFICIENCY = ("none", "partial", "full")
POSTURES = ("adequate", "remediate", "escalate", "defer")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(obj: object) -> str:
    """Canonical JSON for audit hashes; unexpected values fail closed."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _latest_assessments(claims: Iterable[dict] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in claims or []:
        if not isinstance(c, dict) or not c.get("claim_id"):
            continue
        # v0.6 claims may expose a single current assessment or a list of append-only assessments.
        assessments = c.get("grounding_assessments") or c.get("assessments")
        if isinstance(assessments, list) and assessments:
            out[str(c["claim_id"])] = assessments[-1]
        elif isinstance(c.get("grounding_assessment"), dict):
            out[str(c["claim_id"])] = c["grounding_assessment"]
        elif c.get("evidence_assessment"):
            out[str(c["claim_id"])] = {"status": c.get("evidence_assessment")}
    return out


def _probe_summary(probes: Iterable[dict] | None) -> dict:
    probes = [p for p in (probes or []) if isinstance(p, dict)]
    ready = [p for p in probes if p.get("status") in {"ready", "executed", "resolved"}]
    resolved = [p for p in probes if p.get("status") == "resolved"]
    falsified = [p for p in resolved if p.get("result") in {"falsified", "failed", "contradicted"}]
    unresolved = [p for p in ready if p.get("status") != "resolved"]
    return {"count": len(probes), "ready_or_executed": len(ready), "resolved": len(resolved),
            "falsified": len(falsified), "unresolved": len(unresolved),
            "types": dict(Counter(str(p.get("probe_type")) for p in probes))}


def _challenge_summary(challenges: Iterable[dict] | None) -> dict:
    rows = [c for c in (challenges or []) if isinstance(c, dict)]

    def strength(c: dict):
        return c.get("challenge_strength") or c.get("strength")

    def is_unresolved(c: dict) -> bool:
        # Explicit resolution wins over stale status so a resolved challenge cannot
        # accidentally remain a blocker after projection/replay.
        if c.get("resolution") in {"accepted", "accept", "rejected", "reject"}:
            return False
        return c.get("status", "open") in {"open", "unresolved", "pending"}

    strong = [c for c in rows if strength(c) == "strong"]
    unresolved_strong = [c for c in strong if is_unresolved(c)]
    accepted = [c for c in rows if c.get("resolution") in {"accepted", "accept"}]
    unresolved_any = [c for c in rows if is_unresolved(c)]
    return {
        "count": len(rows),
        "strong": len(strong),
        "accepted": len(accepted),
        "unresolved": len(unresolved_any),
        "unresolved_strong": len(unresolved_strong),
    }


def consistency(*, proposed: dict | None, reviewer_read: dict | None, decision: dict | None) -> dict:
    """Compare the three governance positions without treating any model rating as authority."""
    p = (proposed or {}).get("sufficiency")
    r = (reviewer_read or {}).get("sufficiency")
    d = (decision or {}).get("sufficiency")
    return {"assessor": p, "reviewer_read": r, "final": d,
            "assessor_reviewer_agree": p is None or r is None or p == r,
            "reviewer_final_agree": r is None or d is None or r == d,
            "assessor_final_agree": p is None or d is None or p == d}


def precedent_signal(history: Iterable[dict] | None, *, control_id: str) -> dict:
    """Summarise prior concluded cycles for the same control.

    History is supplied by the event projection; no external model is used. A repeated partial/
    none outcome is a recurring deficiency signal, while repeated full is a stable-positive signal.
    """
    rows = [h for h in (history or []) if isinstance(h, dict) and h.get("control_id") == control_id]
    # Prefer the event sequence captured by the projection. For external callers, fall back
    # to a stable timestamp/id ordering rather than trusting iterable insertion order.
    rows.sort(key=lambda h: (
        h.get("decision_event_index") if isinstance(h.get("decision_event_index"), int) else 10**18,
        str(h.get("decision_recorded_at") or h.get("updated") or ""),
        str(h.get("decision_event_id") or ""),
    ))
    ratings = [h.get("decision", {}).get("sufficiency") for h in rows if h.get("decision")]
    ratings = [x for x in ratings if x in SUFFICIENCY]
    last = ratings[-1] if ratings else None
    deficient = sum(x in {"none", "partial"} for x in ratings)
    recurring = len(ratings) >= 2 and deficient >= 2
    deteriorating = len(ratings) >= 2 and SUFFICIENCY.index(last) < SUFFICIENCY.index(ratings[-2])
    return {"prior_cycles": len(ratings), "ratings": ratings, "last_rating": last,
            "recurring_deficiency": recurring, "deteriorating": deteriorating,
            "stable_positive": len(ratings) >= 2 and all(x == "full" for x in ratings[-2:])}


def evaluate(*, control_id: str, reviewer_decision: dict, claims: Iterable[dict] | None = None,
             challenges: Iterable[dict] | None = None, probes: Iterable[dict] | None = None,
             proposed: dict | None = None, reviewer_read: dict | None = None,
             history: Iterable[dict] | None = None,
             challenge_run: dict | None = None) -> dict:
    """Compile a deterministic governance posture for a proposed human decision.

    ``challenge_run`` is the challenger's own envelope, not its rows.  It is read only for
    ``validation_status``: a run whose output was rejected by structured validation returns
    ``challenges: []``, which is byte-identical to a clean run that found nothing to say.
    compare.py already refuses to let a failed assessor call look like agreement (WB-102
    extends the same rule here) — a challenge pass that did not happen must not be able to
    clear a ``full`` rating.
    """
    if not isinstance(reviewer_decision, dict):
        raise ValueError("reviewer decision must be an object")
    suff = reviewer_decision.get("sufficiency")
    if suff not in SUFFICIENCY:
        raise ValueError("DECISION_SUFFICIENCY_INVALID")

    claim_rows = [c for c in (claims or []) if isinstance(c, dict)]
    challenge_rows = sorted(
        (c for c in (challenges or []) if isinstance(c, dict)),
        key=lambda c: str(c.get("challenge_id") or c.get("id") or ""),
    )
    probe_rows = sorted(
        (p for p in (probes or []) if isinstance(p, dict)),
        key=lambda p: str(p.get("probe_id") or p.get("id") or ""),
    )
    assessments = _latest_assessments(claim_rows)
    assessments = dict(sorted(assessments.items(), key=lambda kv: kv[0]))
    challenged = _challenge_summary(challenge_rows)
    falsification = _probe_summary(probe_rows)
    prec = precedent_signal(history, control_id=control_id)
    cons = consistency(proposed=proposed, reviewer_read=reviewer_read, decision=reviewer_decision)

    blockers: list[str] = []
    escalations: list[str] = []
    signals: list[str] = []

    # A final "full" rating cannot silently ignore an unresolved strong contradiction.
    if suff == "full" and any(v.get("status") == "contradicted" for v in assessments.values()):
        blockers.append("CONTRADICTED_CLAIM_REMAINS")
    if suff == "full" and falsification["falsified"]:
        blockers.append("FALSIFICATION_PROBE_FAILED")
    if suff == "full" and challenged["unresolved_strong"]:
        blockers.append("STRONG_CHALLENGE_UNRESOLVED")

    # WB-102: an empty challenge list means one of two different things.  Only the envelope
    # can tell them apart, so silence is treated as a result only when the run completed.
    run = challenge_run if isinstance(challenge_run, dict) else {}
    challenge_blocked = str(run.get("validation_status") or "").lower() == "blocked"
    challenge_ran = bool(run) and not challenge_blocked
    if suff == "full" and challenge_blocked:
        blockers.append("CHALLENGE_RUN_BLOCKED")

    if falsification["unresolved"]:
        signals.append("FALSIFICATION_UNRESOLVED")
    if challenged["unresolved"]:
        signals.append("CHALLENGE_UNRESOLVED")
    if prec["recurring_deficiency"]:
        escalations.append("RECURRING_DEFICIENCY")
    if prec["deteriorating"]:
        escalations.append("LONGITUDINAL_DETERIORATION")
    if not cons["reviewer_final_agree"]:
        signals.append("REVIEWER_REVISED_POSITION")
    if challenge_blocked:
        signals.append("CHALLENGE_RUN_BLOCKED")

    if blockers:
        posture = "defer"
    elif escalations:
        posture = "escalate"
    elif suff == "full":
        posture = "adequate"
    else:
        posture = "remediate"

    ch_rows = challenge_rows
    pr_rows = probe_rows
    basis = {
        "engine_version": "0.8.1",
        "control_id": control_id,
        "decision": reviewer_decision,
        "claims_latest_assessments": assessments,
        "challenges": ch_rows,
        "probes": pr_rows,
        "precedent": prec,
        "challenge_validation_status": run.get("validation_status") if run else None,
    }

    return {
        "schema": "v0.8.governance-decision-engine.1",
        "decision_engine_version": "0.8.1",
        "control_id": control_id,
        "posture": posture,
        "decision_eligible": not blockers,
        "blockers": blockers,
        "escalations": escalations,
        "signals": signals,
        "consistency": cons,
        "precedent": prec,
        "challenge_summary": dict(challenged, run_completed=challenge_ran if run else None,
                                  validation_status=run.get("validation_status") if run else None,
                                  validation_error=run.get("validation_error") if run else None),
        "falsification_summary": falsification,
        "claim_assessment_summary": {
            "claims": len(assessments),
            "statuses": dict(Counter(str(v.get("status")) for v in assessments.values()))
        },
        "basis_hash": _digest(basis),
        "basis": basis,
        "evaluated_at": _now(),
    }


def enforce(evaluation: dict) -> dict:
    """Raise on a hard governance blocker; otherwise return the evaluation."""
    if not evaluation.get("decision_eligible", False):
        raise ValueError("DECISION_BLOCKED:" + ",".join(evaluation.get("blockers") or ["UNKNOWN_BLOCKER"]))
    return evaluation
