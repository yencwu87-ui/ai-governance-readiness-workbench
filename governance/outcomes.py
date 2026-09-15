"""Deterministic, fail-closed outcome and capability evaluation for Lane A."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml
import events

ROOT = Path(__file__).resolve().parent
OUTCOMES_PATH = ROOT / "outcomes.yaml"
CROSSWALK_PATH = ROOT / "crosswalk_mas_mgf.yaml"
CAPABILITIES_PATH = ROOT / "capabilities.yaml"
CONTRACT_DIR = ROOT / "knowledge" / "contracts"


def _canon_fw(fw: str) -> str:
    f = str(fw or "").strip().upper()
    if f.startswith("MGF"):
        return "MGF"
    if f.startswith("MAS"):
        return "MAS"
    return f


def _ck(framework: str, control_id: str) -> str:
    fw = _canon_fw(framework)
    cid = str(control_id or "").strip()
    return f"{fw}::{cid}" if fw else cid


def _load_uncached(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=32)
def _load_cached(path_str: str, mtime_ns: int) -> dict[str, Any]:
    return _load_uncached(Path(path_str))


def _load(path: Path) -> dict[str, Any]:
    # Cached YAML must never be returned by reference: callers/tests may mutate their copy.
    return deepcopy(_load_cached(str(path), path.stat().st_mtime_ns))


def load_catalog() -> dict[str, Any]:
    return _load(OUTCOMES_PATH)


def load_crosswalk() -> dict[str, Any]:
    return _load(CROSSWALK_PATH)


def load_capabilities() -> dict[str, Any]:
    return _load(CAPABILITIES_PATH)


def outcome_definitions() -> list[dict[str, Any]]:
    return list(load_catalog().get("outcomes", []))


def mappings_for(outcome_id: str) -> list[dict[str, Any]]:
    rows = [
        m for m in load_crosswalk().get("mappings", []) or []
        if outcome_id in (m.get("maps_to") or {}).get("outcomes", [])
    ]
    return sorted(rows, key=lambda m: (
        _canon_fw(m.get("framework", "")),
        str(m.get("control_id", "")),
        str(m.get("element_id", "")),
    ))


def capability_definitions() -> list[dict[str, Any]]:
    return list(load_capabilities().get("capabilities", []))


def capability_ids() -> set[str]:
    return {
        str(x.get("capability_id"))
        for x in capability_definitions()
        if x.get("capability_id")
    }


def crosswalk_validation() -> list[dict[str, Any]]:
    """Validate every crosswalk pointer; mappings never disappear silently."""
    contracts: dict[str, dict[str, dict[str, Any]]] = {}
    for filename in ("mas.yaml", "mgf_agentic.yaml"):
        path = CONTRACT_DIR / filename
        if not path.exists():
            continue
        doc = _load(path)
        fw = _canon_fw(doc.get("framework", ""))
        contracts.setdefault(fw, {})
        for c in doc.get("controls", []) or []:
            contracts[fw][str(c.get("control_id"))] = c

    known_caps = capability_ids()
    known_outcomes = {
        str(o.get("outcome_id")) for o in outcome_definitions() if o.get("outcome_id")
    }
    errors: list[dict[str, Any]] = []
    rows = load_crosswalk().get("mappings", []) or []
    for i, m in enumerate(rows):
        fw = _canon_fw(m.get("framework", ""))
        cid = str(m.get("control_id", "")).strip()
        eid = str(m.get("element_id", "")).strip()
        control = contracts.get(fw, {}).get(cid)
        if control is None:
            errors.append({
                "code": "CROSSWALK_DANGLING_POINTER",
                "row": i,
                "framework": fw,
                "control_id": cid,
                "element_id": eid,
                "reason": "control_id not present in governed requirement catalog",
            })
            continue
        element_ids = {str(e.get("id")) for e in control.get("elements", []) or []}
        if eid not in element_ids:
            errors.append({
                "code": "CROSSWALK_DANGLING_POINTER",
                "row": i,
                "framework": fw,
                "control_id": cid,
                "element_id": eid,
                "reason": "element_id not present on governed control",
            })
        for cap in (m.get("maps_to") or {}).get("capabilities", []) or []:
            if str(cap) not in known_caps:
                errors.append({
                    "code": "CROSSWALK_UNKNOWN_CAPABILITY",
                    "row": i,
                    "framework": fw,
                    "control_id": cid,
                    "element_id": eid,
                    "capability_id": cap,
                    "reason": "capability_id not present in capability catalog",
                })
        for outcome_id in (m.get("maps_to") or {}).get("outcomes", []) or []:
            if str(outcome_id) not in known_outcomes:
                errors.append({
                    "code": "CROSSWALK_UNKNOWN_OUTCOME",
                    "row": i,
                    "framework": fw,
                    "control_id": cid,
                    "element_id": eid,
                    "outcome_id": outcome_id,
                    "reason": "outcome_id not present in outcome catalog",
                })

    for outcome in outcome_definitions():
        for cap in outcome.get("capabilities", []) or []:
            if str(cap) not in known_caps:
                errors.append({
                    "code": "OUTCOME_UNKNOWN_CAPABILITY",
                    "outcome_id": outcome.get("outcome_id"),
                    "capability_id": cap,
                    "reason": "capability_id not present in capability catalog",
                })

    return sorted(
        errors,
        key=lambda x: (
            x.get("code", ""),
            str(x.get("outcome_id", "")),
            x.get("row", -1),
            x.get("framework", ""),
            x.get("control_id", ""),
            x.get("element_id", ""),
            x.get("capability_id", ""),
        ),
    )


def authoritative_decisions() -> dict[str, dict[str, Any]]:
    """Latest decided cycle per framework/control, projected only from the event log."""
    out: dict[str, dict[str, Any]] = {}
    rows = sorted(
        events.decided(),
        key=lambda x: (
            str(x.get("decision_recorded_at") or ""),
            str(x.get("decision_event_index") or ""),
            str(x.get("cycle_id") or ""),
        ),
    )
    for row in rows:
        cid = str(row.get("control_id") or "").strip()
        if not cid:
            continue
        out[_ck(row.get("framework", ""), cid)] = dict(row.get("decision") or {})
    return dict(sorted(out.items()))


def _decision_status(decision: dict[str, Any] | None) -> tuple[str, bool, bool, list[str]]:
    if not decision:
        return "unresolved", False, False, []
    gd = decision.get("governance_decision") or {}
    blockers = sorted({str(x) for x in (gd.get("blockers") or [])})
    esc = sorted({str(x) for x in (gd.get("escalations") or [])})
    if blockers or gd.get("decision_eligible") is False:
        return "blocked", True, bool(esc), blockers
    if esc or str(gd.get("posture", "")).lower() == "escalate":
        return "escalate", False, True, esc
    suff = str(decision.get("sufficiency", "")).lower()
    if suff == "full":
        return "full", False, False, []
    if suff in {"partial", "none"}:
        return suff, False, False, []
    return "unresolved", False, False, []


def _sorted_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda x: (
            _canon_fw(x.get("framework", "")),
            str(x.get("control_id", "")),
            str(x.get("element_id", "")),
        ),
    )


def _mapping_item(m: dict[str, Any], decisions_by_control_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    framework = _canon_fw(m.get("framework", ""))
    control_id = str(m.get("control_id", "")).strip()
    element_id = str(m.get("element_id", "")).strip()
    decision = decisions_by_control_key.get(_ck(framework, control_id))
    status, _, _, codes = _decision_status(decision)
    return {
        "framework": framework,
        "control_id": control_id,
        "element_id": element_id,
        "status": status,
        "blockers": codes,
        "evidence_modes": sorted(str(x) for x in (m.get("evidence_modes") or [])),
        "decision": decision or {},
    }


def evaluate_capability(capability_id: str, *, mappings: list[dict[str, Any]],
                        decisions_by_control_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate one capability globally, deduplicating repeated crosswalk bindings."""
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in mappings:
        if capability_id not in ((m.get("maps_to") or {}).get("capabilities", []) or []):
            continue
        item = _mapping_item(m, decisions_by_control_key)
        key = (item["framework"], item["control_id"], item["element_id"])
        if key not in by_key:
            by_key[key] = item
        else:
            by_key[key]["evidence_modes"] = sorted(set(by_key[key].get("evidence_modes", [])) | set(item.get("evidence_modes", [])))
    items = _sorted_items(list(by_key.values()))
    if any(x["status"] == "blocked" for x in items):
        status = "blocked"
    elif any(x["status"] == "escalate" for x in items):
        status = "escalate"
    elif items and all(x["status"] == "full" for x in items):
        status = "supported"
    else:
        status = "insufficient"
    return {
        "capability_id": capability_id,
        "status": status,
        "items": items,
        "mapped_count": len(items),
        "full_count": sum(1 for x in items if x["status"] == "full"),
    }


def evaluate_capabilities_global(*, decisions_by_control_key: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Evaluate every catalogued capability once over the full crosswalk."""
    mappings = load_crosswalk().get("mappings", []) or []
    all_cap_ids = capability_ids()
    rows: dict[str, dict[str, Any]] = {}
    for cap in sorted(all_cap_ids):
        rows[cap] = evaluate_capability(
            cap,
            mappings=mappings,
            decisions_by_control_key=decisions_by_control_key,
        )
    return rows


def _outcome_capability_ids(outcome_id: str) -> list[str]:
    for outcome in outcome_definitions():
        if str(outcome.get("outcome_id")) == outcome_id:
            return sorted({str(x) for x in (outcome.get("capabilities") or [])})
    return []


def _mapped_rows_for_capabilities(outcome_id: str, capability_status: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    outcome_caps = set(_outcome_capability_ids(outcome_id))
    rows: list[dict[str, Any]] = []
    for cap in sorted(outcome_caps):
        for item in capability_status.get(cap, {}).get("items", []):
            row = dict(item)
            row["capability_id"] = cap
            rows.append(row)
    return _sorted_items(rows)


def _next_action_for_item(item: dict[str, Any]) -> str:
    ref = f"{item['framework']} {item['control_id']}.{item['element_id']}"
    modes = ", ".join(item.get("evidence_modes") or []) or "governed evidence"
    if item["status"] == "blocked":
        codes = ", ".join(item.get("blockers") or []) or "GOVERNANCE_BLOCKER"
        return f"Resolve {codes} for {ref} (use: {modes})"
    if item["status"] == "escalate":
        return f"Escalate {ref} and review longitudinal signals (use: {modes})"
    if item["status"] == "unresolved":
        return f"Record a governed decision for {ref} (evidence mode: {modes})"
    if item["status"] in {"partial", "none"}:
        return f"Provide additional evidence for {ref} (evidence mode: {modes})"
    return f"Review {ref}"


def evaluate_outcome(outcome_id: str, *, decisions_by_control_key: dict[str, dict[str, Any]],
                     capability_status: dict[str, dict[str, Any]] | None = None,
                     control_key_for: Callable[[str, str], str] | None = None) -> dict[str, Any]:
    del control_key_for  # retained for API compatibility.
    validation = crosswalk_validation()
    all_mappings = load_crosswalk().get("mappings", []) or []
    relevant_rows = {
        i for i, m in enumerate(all_mappings)
        if outcome_id in ((m.get("maps_to") or {}).get("outcomes", []))
    }
    relevant_errors = [
        e for e in validation
        if e.get("outcome_id") == outcome_id or e.get("row") in relevant_rows
    ]
    mappings = mappings_for(outcome_id)
    if not mappings:
        return {
            "outcome_id": outcome_id,
            "posture": "defer",
            "posture_code": "OUTCOME_NO_MAPPINGS",
            "errors": [{"code": "OUTCOME_NO_MAPPINGS"}],
            "mapped_items": [],
            "capabilities": {},
            "next_actions": ["Add governed outcome mappings."],
            "next_action": "Add governed outcome mappings.",
            "mapped_count": 0,
            "full_count": 0,
        }

    caps = capability_status or evaluate_capabilities_global(decisions_by_control_key=decisions_by_control_key)
    outcome_cap_ids = _outcome_capability_ids(outcome_id)
    outcome_caps = {cap: caps.get(cap, {"capability_id": cap, "status": "insufficient", "items": [], "mapped_count": 0})
                    for cap in outcome_cap_ids}
    items = _mapped_rows_for_capabilities(outcome_id, caps)

    blockers = sorted({b for x in items for b in x.get("blockers", [])})
    if relevant_errors:
        posture = "defer"
        posture_code = "MAPPING_INVALID"
    elif blockers or any(v.get("status") == "blocked" for v in outcome_caps.values()):
        posture = "defer"
        posture_code = blockers[0] if blockers else "CAPABILITY_BLOCKED"
    elif any(v.get("status") == "escalate" for v in outcome_caps.values()):
        posture = "escalate"
        posture_code = "LONGITUDINAL_OR_GOVERNANCE_ESCALATION"
    elif outcome_caps and all(v.get("status") == "supported" for v in outcome_caps.values()):
        posture = "adequate"
        posture_code = "ALL_REQUIRED_CAPABILITIES_SUPPORTED"
    else:
        posture = "remediate"
        posture_code = "REQUIRED_CAPABILITY_INSUFFICIENT"

    candidates = [x for x in items if x["status"] != "full"]
    next_actions = sorted({_next_action_for_item(x) for x in candidates})
    if not next_actions:
        insufficient_caps = sorted(k for k, v in outcome_caps.items() if v.get("status") == "insufficient")
        next_actions = [f"Provide evidence for capability {insufficient_caps[0]}"] if insufficient_caps else ["Maintain evidence and monitor for change."]

    return {
        "outcome_id": outcome_id,
        "posture": posture,
        "posture_code": posture_code,
        "errors": relevant_errors,
        "mapped_items": items,
        "capabilities": outcome_caps,
        "next_actions": next_actions,
        "next_action": next_actions[0],
        "mapped_count": len(items),
        "full_count": sum(1 for x in items if x["status"] == "full"),
    }


def evaluate_all() -> list[dict[str, Any]]:
    decisions = authoritative_decisions()
    capability_status = evaluate_capabilities_global(decisions_by_control_key=decisions)
    return [
        evaluate_outcome(
            str(o.get("outcome_id")),
            decisions_by_control_key=decisions,
            capability_status=capability_status,
        )
        for o in sorted(outcome_definitions(), key=lambda x: str(x.get("outcome_id", "")))
    ]
