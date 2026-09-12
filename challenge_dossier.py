"""Append-only Challenge My Read dossiers.

A dossier records the challenge as a review object: the reviewer's read, the generated
structured challenges, the governance knowledge consulted, and the human response to each
challenge. It never changes a governance rating and never writes to the playbook.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "governance" / "challenge_dossiers.jsonl"
RESPONSES = ("accept", "reject", "evidence_provided", "escalate")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def create_dossier(*, control_id: str, control_title: str, reviewer: str, blind: dict,
                   challenges: list[dict], challenger_model: str | None, knowledge: list[dict],
                   assessment_id: str | None = None, reasoning_schema: str | None = None) -> dict:
    """Create a dossier snapshot. Challenge responses start as open and are filled by the reviewer."""
    if not reviewer.strip():
        raise ValueError("a named reviewer is required")
    if not isinstance(challenges, list):
        raise ValueError("challenges must be a list")
    dossier = {
        "dossier_id": f"CHD-{_digest({'control_id': control_id, 'reviewer': reviewer, 'blind': blind, 'challenges': challenges, 'at': _now()})}",
        "created_at": _now(),
        "control_id": control_id,
        "control_title": control_title,
        "reviewer": reviewer.strip(),
        "reviewer_read": dict(blind or {}),
        "challenger_model": challenger_model,
        "reasoning_schema": reasoning_schema,
        "assessment_id": assessment_id,
        "knowledge": list(knowledge or []),
        "challenge_outcome": "substantive" if any((c.get("challenge_strength") == "strong") for c in challenges) else ("weak_or_refining" if challenges else "no_challenges"),
        "challenges": [],
        "status": "open" if challenges else "no_challenges",
    }
    for idx, item in enumerate(challenges, 1):
        dossier["challenges"].append({
            "challenge_no": idx,
            "severity": item.get("severity", "medium"),
            "confidence": item.get("confidence", "medium"),
            "observation": item.get("observation", ""),
            "evidence_basis": list(item.get("evidence_basis", [])),
            "requirement_basis": list(item.get("requirement_basis", [])),
            "knowledge_basis": list(item.get("knowledge_basis", [])),
            "inference": item.get("inference", ""),
            "challenge": item.get("challenge", ""),
            "factual_pointer": dict(item.get("factual_pointer") or {}),
            "requirement_pointer": dict(item.get("requirement_pointer") or {}),
            "claim_test": dict(item.get("claim_test") or {}),
            "challenge_strength": item.get("challenge_strength", "weak"),
            "risk_to_address": item.get("risk_to_address", ""),
            "resolution_pointer": item.get("resolution_pointer", ""),
            "recommended_action": item.get("recommended_action", "answer"),
            "response": None,
        })
    return dossier


def respond(dossier: dict, challenge_no: int, *, response: str, reviewer: str,
            note: str, evidence: list[str] | None = None) -> dict:
    """Return a new dossier revision with one challenge response recorded.

    The original dossier is not mutated on disk; callers append the returned snapshot.
    """
    if response not in RESPONSES:
        raise ValueError(f"response must be one of {RESPONSES}")
    if not reviewer.strip():
        raise ValueError("a named reviewer is required")
    if not note.strip() and response != "evidence_provided":
        raise ValueError("a response note is required")
    out = json.loads(json.dumps(dossier))
    target = next((c for c in out.get("challenges", []) if c.get("challenge_no") == challenge_no), None)
    if target is None:
        raise ValueError(f"challenge {challenge_no} not found")
    target["response"] = {
        "recorded_at": _now(),
        "reviewer": reviewer.strip(),
        "disposition": response,
        "note": note.strip(),
        "evidence": [str(x).strip() for x in (evidence or []) if str(x).strip()],
    }
    responses = [c.get("response") for c in out.get("challenges", [])]
    out["status"] = "closed" if responses and all(responses) else "partially_addressed"
    out["last_updated_at"] = _now()
    return out


def append(dossier: dict, path: Path = LOG) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dossier, ensure_ascii=False) + "\n")
    return dossier


def load(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def latest_dossier(control_id: str, path: Path = LOG) -> dict | None:
    rows = [r for r in load(path) if r.get("control_id") == control_id]
    return rows[-1] if rows else None


def latest_by_id(dossier_id: str, path: Path = LOG) -> dict | None:
    rows = [r for r in load(path) if r.get("dossier_id") == dossier_id]
    return rows[-1] if rows else None
