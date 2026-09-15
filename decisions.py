"""Step decisions — the only write path out of the lifecycle cards.

Append-only JSONL at governance/step_decisions.jsonl. One record per reviewer click.
The judge's proposal is stored alongside the decision so judge-vs-reviewer disagreement can
be measured later (see calibration()).

Gate logic: a play's exit gate is 'passed' only when every step of that play has a recorded
decision and none is 'reject'. Play N+1 is 'locked' until Play N's gate has passed.

Reason validation lives in reasons.py, not here. It used to be three inline checks in this
function, a separate _thin() in eval/label.py with a different word list, and nothing at all
in Lane A. Three dialects of one rule, and the weakest guarded the lane with the most records.
The rule is now stated once and imported by every write path.

The check is stricter than the one it replaces. It rejects placeholders ("none", "ok", "as
above") that the old check let through, and it rejects a reason that only says a model was
persuasive. That will fail some reviewers mid-flow. It is meant to: 47 of the 51 records
already in the log carry the decision word in the reason field, and they cannot be honestly
retro-filled.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from reasons import reason_error

LOG = Path(__file__).parent / "governance" / "step_decisions.jsonl"
DECISIONS = ("accept", "amend", "reject")


def _canon(obj) -> str:
    """Governance canonical JSON: stable keys, Unicode, and no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(obj) -> str | None:
    if obj is None:
        return None
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


@contextmanager
def _append_lock(path: Path):
    """Serialize JSONL appends on POSIX filesystems without adding a dependency."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(uc_id: str, step_id: str, decision: str, reviewer: str, reason: str,
           proposal: dict | None, final: dict | None, path: Path = LOG,
           *, blind: dict | None = None) -> dict:
    """Write one decision. `final` is the sufficiency/gaps the reviewer actually recorded
    (equal to the proposal on accept, edited on amend, reviewer-supplied on reject).

    `blind` is the reviewer's own reading of the step, recorded before the judge ran, where
    the caller has one. Optional, so existing callers are unaffected. When it is supplied and
    the decision departs from it, the reason is held to the revision standard — a changed
    rating carrying an unchanged reason is refused — and `supersedes` is written so a decision
    that moved after seeing a machine is distinguishable from one that never moved.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if not str(uc_id).strip():
        raise ValueError("uc_id is required")
    if not str(step_id).strip():
        raise ValueError("step_id is required")
    if not reviewer.strip():
        raise ValueError("a named reviewer is required")
    if decision in ("accept", "amend") and final is None:
        raise ValueError("final is required for accept/amend")

    moved = bool(blind and final and (
        blind.get("sufficiency") != final.get("sufficiency")
        or blind.get("maturity") != final.get("maturity")))
    err = reason_error(reason, rating=decision,
                       revised=moved, previous=(blind or {}).get("reason"))
    if err:
        raise ValueError(err)

    rec = {
        "recorded_at": _now(),
        "use_case": uc_id,
        "step": step_id,
        "decision": decision,
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "proposal": proposal,
        "final": final,
        "proposal_hash": _hash(proposal),
        "proposal_hash16": (_hash(proposal) or "")[:16] if proposal else None,
        "final_hash": _hash(final),
        "blind_hash": _hash(blind),
    }
    if blind:
        rec["blind"] = dict(blind)
        if moved:
            rec["supersedes"] = {k: blind.get(k) for k in ("sufficiency", "maturity", "reason")}
    with _append_lock(path):
        with path.open("a", encoding="utf-8") as f:
            f.write(_canon(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return rec


def load(path: Path = LOG) -> list[dict]:
    """Load valid records while tolerating isolated corrupt/truncated lines."""
    if not path.exists():
        return []
    records, _ = _load_with_errors(path)
    return records


def _load_with_errors(path: Path) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    errors: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                errors.append({"line": lineno, "error": str(exc), "raw": line.rstrip("\n")})
    return records, errors


def load_errors(path: Path = LOG) -> list[dict]:
    """Return parse errors without preventing valid records from being read."""
    if not path.exists():
        return []
    return _load_with_errors(path)[1]


def latest(uc_id: str, path: Path = LOG) -> dict[str, dict]:
    """Newest decision per step for a use case."""
    out: dict[str, dict] = {}
    for r in load(path):
        if r["use_case"] == uc_id:
            out[r["step"]] = r          # file is chronological; last wins
    return out


def hollow(path: Path = LOG) -> list[dict]:
    """Records whose reason would not pass the current rule.

    The log is append-only and these cannot be corrected, so they are surfaced rather than
    fixed. Anything this returns is a decision with a name and a timestamp but no rationale,
    and should be read as unevidenced when the log is used as an accountability record.
    """
    out = []
    for r in load(path):
        e = reason_error(r.get("reason", ""), rating=r.get("decision"))
        if e:
            out.append({"recorded_at": r.get("recorded_at"), "use_case": r.get("use_case"),
                        "step": r.get("step"), "decision": r.get("decision"),
                        "reviewer": r.get("reviewer"), "reason": r.get("reason"), "why": e})
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
    """Judge-vs-reviewer agreement, overall and per play. Lane-B-fed (deterministic) proposals are
    excluded — they measure the control, not the judge. Amend/reject with a proposal count as
    disagreement; the sufficiency delta says whether the judge over- or under-rates.

    `blind_agree` counts only records carrying the reviewer's prior reading. Plain `agree` cannot
    separate a reviewer who reached the judge's rating independently from one who accepted a
    pre-filled default, so on records with no blind reading it measures the interface as much as
    the judge. Read `agree` as an upper bound and `blind_agree` as the real figure.
    """
    rank = {"none": 0, "partial": 1, "full": 2}
    rows = [r for r in load(path) if r.get("proposal") and r["proposal"].get("source") != "lane_b"]
    per: dict[str, dict] = {}
    for r in rows:
        play = r["step"].split(".")[0]
        d = per.setdefault(play, {"n": 0, "agree": 0, "over": 0, "under": 0, "same": 0,
                                  "blind_n": 0, "blind_agree": 0, "moved": 0, "moved_rating": 0})
        d["n"] += 1
        if r["decision"] == "accept":
            d["agree"] += 1
        else:
            ps = rank.get((r["proposal"] or {}).get("sufficiency", ""), 1)
            fs = rank.get((r["final"] or {}).get("sufficiency", ""), 1)
            if ps > fs:
                d["over"] += 1
            elif ps < fs:
                d["under"] += 1
            else:
                d["same"] += 1
        if r.get("blind"):
            d["blind_n"] += 1
            if r["blind"].get("sufficiency") == (r["proposal"] or {}).get("sufficiency"):
                d["blind_agree"] += 1
            if r.get("supersedes"):
                d["moved"] += 1
                d["moved_rating"] += 1
    total = {"n": len(rows),
             "agree": sum(v["agree"] for v in per.values()),
             "blind_n": sum(v["blind_n"] for v in per.values()),
             "blind_agree": sum(v["blind_agree"] for v in per.values()),
             "moved": sum(v["moved"] for v in per.values())}
    return {"total": total, "per_play": per}


# ---- tolerant accessors: plays may be objects or dicts --------------------------------
def _get(o, k, default=None):
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)

def _pid(p): return _get(p, "id")
def _steps(p): return _get(p, "steps", []) or []
def _sid(s): return _get(s, "id")
