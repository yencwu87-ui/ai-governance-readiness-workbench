"""Reviewer workflow projection for the Streamlit lane-A experience.

This module deliberately contains no Streamlit calls and no governance mutations. It translates
existing authoritative cycle state plus the UI cache into a deterministic reviewer-facing queue.
"""
from __future__ import annotations


def challenge_counts(state: dict, fallback: dict | None = None) -> dict:
    rows = list(state.get("challenges") or []) if state else []
    if not rows and fallback:
        rows = list(fallback.get("challenges") or [])
    unresolved = 0
    strong = 0
    unresolved_strong = 0
    for row in rows:
        strength = str(row.get("challenge_strength") or row.get("strength") or "weak").lower()
        resolution = str(row.get("resolution") or "").lower()
        status = str(row.get("status") or "open").lower()
        resolved = resolution in {"accepted", "accept", "rejected", "reject", "escalate"} or status == "resolved"
        if not resolved:
            unresolved += 1
            if strength == "strong":
                unresolved_strong += 1
        if strength == "strong":
            strong += 1
    # WB-107: zero rows has three causes and they are not the same fact.
    #   ran cleanly, nothing to say  -> ran=True,  blocked=False
    #   ran, output failed validation-> ran=True,  blocked=True
    #   never ran                    -> ran=False, blocked=False
    # Counting only rows made all three look like "nothing unresolved", which is how a failed
    # challenge came to show a green tick beside "Challenge" in the progress bar.
    envelopes = [r for r in ([*(state.get("challenges") or [])] if state else []) if isinstance(r, dict)]
    if not envelopes and fallback:
        envelopes = [fallback] if isinstance(fallback, dict) else []
    blocked = any(str(e.get("validation_status") or "").lower() == "blocked" for e in envelopes)
    return {"count": len(rows), "unresolved": unresolved, "strong": strong,
            "unresolved_strong": unresolved_strong,
            "ran": bool(envelopes), "blocked": blocked,
            "produced_a_result": bool(envelopes) and not blocked}


def next_action(state: dict, *, local: dict | None = None) -> dict:
    """Return the one deterministic action the reviewer should take next."""
    local = local or {}
    evidence = state.get("evidence") or local.get("evidence") or {}
    has_evidence = bool(evidence.get("text") or evidence.get("file_path") or evidence.get("file_name"))
    read = state.get("read") or local.get("blind")
    proposal = state.get("proposal") or local.get("ai")
    diff = state.get("diff") or local.get("compare")
    decision = state.get("decision") or local.get("decision")
    ch = challenge_counts(state, local.get("challenge"))

    if not has_evidence:
        return {"label": "Add evidence", "anchor": "evidence", "priority": 100, "kind": "input"}
    if not read:
        return {"label": "Record your reading", "anchor": "blind", "priority": 90, "kind": "gate"}
    if not proposal:
        return {"label": "Prepare AI assessment", "anchor": "ai", "priority": 80, "kind": "system"}
    if not diff:
        return {"label": "Review comparison", "anchor": "compare", "priority": 70, "kind": "review"}
    if ch["unresolved_strong"]:
        n = ch["unresolved_strong"]
        return {"label": f"Resolve {n} strong challenge{'s' if n != 1 else ''}", "anchor": "challenges", "priority": 65, "kind": "blocker"}
    if ch["unresolved"]:
        n = ch["unresolved"]
        return {"label": f"Review {n} open challenge{'s' if n != 1 else ''}", "anchor": "challenges", "priority": 60, "kind": "review"}
    if not decision:
        return {"label": "Record decision", "anchor": "decision", "priority": 50, "kind": "decision"}
    return {"label": "Complete", "anchor": None, "priority": 0, "kind": "complete"}


def project_control(control, *, state: dict | None, local: dict | None = None) -> dict:
    state = state or {}
    local = local or {}
    ev = state.get("evidence") or local.get("evidence") or {}
    read = state.get("read") or local.get("blind")
    proposal = state.get("proposal") or local.get("ai")
    diff = state.get("diff") or local.get("compare")
    decision = state.get("decision") or local.get("decision")
    ch = challenge_counts(state, local.get("challenge"))
    action = next_action(state, local=local)
    stage = state.get("stage") or ("decided" if decision else "open")
    return {
        "key": control.key,
        "control_id": control.id,
        "title": control.title,
        "library": control.lib,
        "stage": stage,
        "cycle_id": state.get("cycle_id"),
        "updated": state.get("updated"),
        "has_evidence": bool(ev.get("text") or ev.get("file_path") or ev.get("file_name")),
        # WB-103: whether the completeness pass has run, and what it found. Gaps do not make the
        # step incomplete — the scan having run is the completion, because proceeding with known
        # gaps is a legitimate and recordable choice.
        "has_completeness": bool(state.get("completeness")),
        "completeness_gaps": len(((state.get("completeness") or {}).get("gaps")) or []),
        "completeness_testable": bool((state.get("completeness") or {}).get("testable")),
        "evidence_topped_up": bool(ev.get("evidence_added_after_gap_scan")),
        "has_read": bool(read),
        "has_proposal": bool(proposal),
        "proposal_error": bool(isinstance(proposal, dict) and proposal.get("model") == "error"),
        "has_compare": bool(diff),
        "challenge": ch,
        "decision": bool(decision),
        "next_action": action,
    }


def build_queue(in_scope, *, cycle_states: dict, cache: dict) -> list[dict]:
    rows = []
    for control in in_scope:
        local = {
            "evidence": (cache.get("evidence") or {}).get(control.key, {}),
            "blind": (cache.get("blind") or {}).get(control.key),
            "ai": (cache.get("ai") or {}).get(control.key),
            "compare": (cache.get("compare") or {}).get(control.key),
            "challenge": (cache.get("challenge") or {}).get(control.key),
            "decision": (cache.get("decisions") or {}).get(control.key),
        }
        row = project_control(control, state=cycle_states.get(control.key), local=local)
        rows.append(row)
    rows.sort(key=lambda r: (r["next_action"]["priority"] * -1, 0 if not r["decision"] else 1, r["control_id"]))
    return rows
