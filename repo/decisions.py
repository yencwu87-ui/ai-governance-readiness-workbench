"""Step decisions — the only write path out of the lifecycle cards.

Append-only JSONL at governance/step_decisions.jsonl. One record per reviewer click.
The judge's proposal is stored alongside the decision so judge-vs-reviewer disagreement can
be measured later (see calibration()).

Gate logic: a play's exit gate is 'passed' only when every step of that play has a recorded
decision and none is 'reject'. Play N+1 is 'locked' until Play N's gate has passed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).parent / "governance" / "step_decisions.jsonl"
DECISIONS = ("accept", "amend", "reject")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(uc_id: str, step_id: str, decision: str, reviewer: str, reason: str,
           proposal: dict | None, final: dict | None, path: Path = LOG) -> dict:
    """Write one decision. `final` is the sufficiency/gaps the reviewer actually recorded
    (equal to the proposal on accept, edited on amend, reviewer-supplied on reject)."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not reviewer.strip():
        raise ValueError("a named reviewer is required")
    if decision != "accept" and not reason.strip():
        raise ValueError("a reason is required on amend/reject")
    rec = {
        "recorded_at": _now(),
        "use_case": uc_id,
        "step": step_id,
        "decision": decision,
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "proposal": proposal,
        "final": final,
        "proposal_hash": hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()[:16]
        if proposal else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load(path: Path = LOG) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def latest(uc_id: str, path: Path = LOG) -> dict[str, dict]:
    """Newest decision per step for a use case."""
    out: dict[str, dict] = {}
    for r in load(path):
        if r["use_case"] == uc_id:
            out[r["step"]] = r          # file is chronological; last wins
    return out


def play_status(plays: list, uc_id: str, path: Path = LOG) -> dict[str, str]:
    """Map play id -> not_started | in_progress | gate_passed | gate_failed | locked."""
    lat = latest(uc_id, path)
    status: dict[str, str] = {}
    prev_passed = True
    for p in plays:
        pid, steps = _pid(p), _steps(p)
        decided = [lat.get(_sid(s)) for s in steps]
        if not prev_passed:
            status[pid] = "locked"
        elif all(d is None for d in decided):
            status[pid] = "not_started"
        elif any(d and d["decision"] == "reject" for d in decided):
            status[pid] = "gate_failed"
        elif all(d is not None for d in decided):
            status[pid] = "gate_passed"
        else:
            status[pid] = "in_progress"
        prev_passed = status[pid] == "gate_passed"
    return status


def calibration(path: Path = LOG) -> dict:
    """Judge-vs-reviewer agreement, overall and per play. Amend/reject with a proposal count as
    disagreement; the sufficiency delta says whether the judge over- or under-rates."""
    rank = {"none": 0, "partial": 1, "full": 2}
    rows = [r for r in load(path) if r.get("proposal")]
    per: dict[str, dict] = {}
    for r in rows:
        play = r["step"].split(".")[0]
        d = per.setdefault(play, {"n": 0, "agree": 0, "over": 0, "under": 0})
        d["n"] += 1
        if r["decision"] == "accept":
            d["agree"] += 1
        else:
            ps = rank.get((r["proposal"] or {}).get("sufficiency", ""), 1)
            fs = rank.get((r["final"] or {}).get("sufficiency", ""), 1)
            d["over" if ps > fs else "under"] += 1
    total = {"n": len(rows), "agree": sum(v["agree"] for v in per.values())}
    return {"total": total, "per_play": per}


# ---- tolerant accessors: plays may be objects or dicts --------------------------------
def _get(o, k, default=None):
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)

def _pid(p): return _get(p, "id")
def _steps(p): return _get(p, "steps", []) or []
def _sid(s): return _get(s, "id")
