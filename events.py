"""WB-040 — the append-only event store.

Why this exists
---------------
Lane A decisions lived in `data/assessments.json`, which `save_state()` rewrote whole on every
interaction. A 792 KB mutable blob, last-writer-wins, no per-record durability. An audit record
that is rewritten in full on each click is not an audit record, and the practical consequence
was already felt: a contaminated proposal could not be surgically removed, only edited around.

`governance/step_decisions.jsonl` had it right and only covered the lifecycle lane.

This module is that model for everything, with three properties the JSONL log did not have:

  trace id     Every event in one assessment cycle carries the same `cycle_id`, so a proposal,
               a blind read, a comparison, a challenge and a decision are one retrievable unit
               rather than five records in four files that have to be joined by control id and
               hope.
  hash chain   Each event carries the SHA-256 of the previous event. A deleted or edited line
               breaks the chain at that point and `verify()` names the event where it broke.
               This does not make tampering impossible — anyone who can write the file can
               rewrite the chain — it makes silent tampering detectable, which is the property
               an assurance record actually needs.
  projection   `state()` rebuilds the current view by replaying events. The view is derived,
               never authoritative, so a wrong projection is a bug you can fix by re-reading
               rather than a corrupted record you cannot recover.

Events are immutable. There is no update and no delete. A correction is a new event that
supersedes an earlier one, and both remain readable — which is the point.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parent
LOG = Path(os.environ.get("WB_EVENT_LOG", ROOT / "governance" / "events.jsonl"))

#: The kinds an assessment cycle can contain, in the order they normally occur. `read` may be
#: recorded before or after `proposed` — blindness is about what the reviewer was shown, not
#: about when the model call was made — but `compared` requires both, and `decided` closes.
#: Every event kind the ledger accepts. `append` rejects anything else, deliberately — a new
#: kind must be added here on purpose, not invented by a caller passing a new string.
#:
#: GE-109: `gap_scanned` was missing, so `cycle.gap_scan()` raised on every call from the day it
#: shipped. Nothing caught it because the WB-103 tests exercised `completeness.scan` directly and
#: never went through the cycle. `test_ge109_boundary.py` now asserts that every kind appended
#: anywhere in `core/cycle.py` appears here, so the next omission fails at test time.
KINDS = ("cycle_started", "observed", "evidence_bound", "gap_scanned", "proposed", "read",
         "compared", "challenged", "decided", "superseded", "note")

GENESIS = "0" * 64


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _canon(value: object) -> str:
    """Strict canonical JSON used by the event hash chain. Unexpected values fail closed."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "sha"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


@contextmanager
def _append_lock(path: Path):
    """Serialize the read-last-sha + append pair across processes."""
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def new_cycle_id(control_id: str) -> str:
    """Readable prefix, random suffix. Readable because a person reads these in a log."""
    return f"{control_id.replace(' ', '').replace('.', '-')}-{uuid.uuid4().hex[:10]}"


def read_all(path: Path | None = None) -> list[dict]:
    p = Path(path or LOG)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A malformed line is itself a finding. Keep it visible rather than skipping
            # silently, and let verify() report it.
            out.append({"kind": "__unparseable__", "raw": line[:400]})
    return out


def _last_sha(path: Path) -> str:
    events = read_all(path)
    for e in reversed(events):
        if e.get("sha"):
            return e["sha"]
    return GENESIS


def _canon_framework(framework: str) -> str:
    f = str(framework or "").strip()
    u = f.upper()
    if u.startswith("MGF"):
        return "MGF"
    if u.startswith("MAS"):
        return "MAS"
    return f


def append(kind: str, *, cycle_id: str, actor: str, payload: dict | None = None,
           control_id: str = "", framework: str = "", path: Path | None = None) -> dict:
    """Write one event. Framework keys are canonicalized for MAS/MGF at the write boundary."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r} — add it to KINDS deliberately, "
                         f"not by passing a new string")
    p = Path(path or LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    if kind != "observed" and not str(cycle_id or "").strip():
        raise ValueError("cycle_id must be non-empty")
    if not str(actor or "").strip():
        raise ValueError("actor must be non-empty")
    with _append_lock(p):
        event = {
            "event_id": uuid.uuid4().hex,
            "cycle_id": str(cycle_id).strip(),
            "ts": _now(),
            "kind": kind,
            "actor": str(actor).strip(),
            "control_id": control_id,
            "framework": _canon_framework(framework),
            "payload": payload or {},
            "prev": _last_sha(p),
        }
        event["sha"] = _digest(event)
        line = _canon(event)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return event


def observations(path: Path | None = None) -> list[dict]:
    """Return globally recorded plugin observations. These are not assessment-cycle state."""
    return [e for e in read_all(path) if e.get("kind") == "observed"]


def cycle(cycle_id: str, path: Path | None = None) -> list[dict]:
    return [e for e in read_all(path) if e.get("cycle_id") == cycle_id]


def cycles(path: Path | None = None, control_id: str | None = None) -> list[str]:
    seen: list[str] = []
    for e in read_all(path):
        cid = e.get("cycle_id")
        if not cid or cid in seen:
            continue
        if control_id and e.get("control_id") != control_id:
            continue
        seen.append(cid)
    return seen


def verify(path: Path | None = None) -> dict:
    """Walk the chain. Reports where it breaks rather than asserting it holds."""
    events = read_all(path)
    prev = GENESIS
    broken: list[dict] = []
    unparseable = 0
    for i, e in enumerate(events):
        if e.get("kind") == "__unparseable__":
            unparseable += 1
            broken.append({"index": i, "reason": "line could not be parsed as JSON"})
            continue
        if e.get("prev") != prev:
            broken.append({"index": i, "event_id": e.get("event_id"), "cycle_id": e.get("cycle_id"),
                           "reason": "prev does not match the previous event's sha — an event "
                                     "before this one was edited or removed"})
        if _digest(e) != e.get("sha"):
            broken.append({"index": i, "event_id": e.get("event_id"), "cycle_id": e.get("cycle_id"),
                           "reason": "sha does not match the event body — this event was edited"})
        prev = e.get("sha", prev)
    return {"events": len(events), "unparseable": unparseable,
            "intact": not broken, "breaks": broken}


def state(cycle_id: str, path: Path | None = None) -> dict:
    """Rebuild the current view of one cycle by replaying its events.

    Derived, never authoritative. Later events of the same kind supersede earlier ones, so a
    re-assessment or a revised read is a new event and the history stays readable.
    """
    all_events = read_all(path)
    indexed = [(i, e) for i, e in enumerate(all_events) if e.get("cycle_id") == cycle_id]
    evs = [e for _, e in indexed]
    if not evs:
        return {}
    view: dict = {"cycle_id": cycle_id, "control_id": "", "framework": "",
                  "events": len(evs), "started": evs[0]["ts"], "updated": evs[-1]["ts"],
                  "history": [(e["kind"], e["ts"], e["actor"]) for e in evs]}
    for event_index, e in indexed:
        view["control_id"] = e.get("control_id") or view["control_id"]
        view["framework"] = e.get("framework") or view["framework"]
        k, pl = e["kind"], e.get("payload") or {}
        if k == "observed":
            view.setdefault("observations", []).append(pl.get("observation") or pl)
        elif k == "evidence_bound":
            view["evidence"] = pl
        elif k == "gap_scanned":
            # WB-103: completeness is a bundle fact, not a verdict. Replay keeps the latest one
            # and the stage projection below never treats it as an assessment step.
            view["completeness"] = pl.get("completeness")
        elif k == "proposed":
            view["proposal"] = pl.get("proposal")
            view["assessment_identity"] = pl.get("assessment_identity")
            view["proposal_model"] = pl.get("model")
        elif k == "read":
            view["read"] = pl.get("read")
            view["reader"] = e["actor"]
        elif k == "compared":
            view["diff"] = pl.get("diff")
        elif k == "challenged":
            view.setdefault("challenges", []).append(pl)
            if pl.get("claim_register"):
                view["claim_register"] = pl.get("claim_register")
            if pl.get("falsification_engine"):
                view["falsification_engine"] = pl.get("falsification_engine")
        elif k == "note":
            if pl.get("falsification_engine"):
                view["falsification_engine"] = pl.get("falsification_engine")
            # Challenge responses are append-only corrections to the projected challenge state.
            # They never mutate the original challenge event; replay simply overlays the latest
            # recorded resolution onto the matching challenge number/id.
            for response in pl.get("challenge_responses") or []:
                if not isinstance(response, dict):
                    continue
                target_no = response.get("challenge_no")
                target_id = response.get("challenge_id")
                for challenge in view.get("challenges", []):
                    if (target_id and challenge.get("challenge_id") == target_id) or (
                            target_no is not None and challenge.get("challenge_no") == target_no):
                        if response.get("disposition"):
                            disp = str(response["disposition"]).lower()
                            challenge["resolution"] = {
                                "accept": "accepted", "reject": "rejected",
                                "evidence_provided": "accepted", "escalate": "escalate",
                            }.get(disp, disp)
                        if response.get("status"):
                            challenge["status"] = response["status"]
                        challenge["response"] = {k_: response[k_] for k_ in ("disposition", "note", "evidence") if k_ in response}
        elif k == "decided":
            view["decision"] = pl
            view["decided_by"] = e["actor"]
            # Preserve the append-log ordering metadata needed for deterministic longitudinal
            # analysis. Timestamp alone is insufficient when multiple cycles close in one second.
            view["decision_recorded_at"] = e.get("ts")
            view["decision_event_id"] = e.get("event_id")
            view["decision_event_index"] = event_index
        elif k == "superseded":
            view["superseded_by"] = pl.get("cycle_id")
    view["stage"] = _stage(view)
    return view


def _stage(view: dict) -> str:
    if view.get("superseded_by"):
        return "superseded"
    if view.get("decision"):
        return "decided"
    if view.get("read") and view.get("proposal"):
        return "comparable"
    if view.get("read"):
        return "read recorded"
    if view.get("proposal"):
        return "proposed, awaiting a blind read"
    return "open"


def iter_states(path: Path | None = None) -> Iterator[dict]:
    for cid in cycles(path):
        yield state(cid, path)


def decided(path: Path | None = None) -> list[dict]:
    """Every cycle that reached a human decision — the population a replay runs over."""
    return [s for s in iter_states(path) if s.get("stage") == "decided"]


def export_projection(path: Path | None = None) -> dict:
    """The shape `data/assessments.json` held, rebuilt from events.

    Provided so the projection can replace the blob rather than sit beside it: whatever reads
    the old file can read this, and the file stops being the source of truth.
    """
    out: dict = {"decisions": {}, "ai": {}, "blind": {}, "evidence": {}}
    for s in iter_states(path):
        key = s.get("control_id")
        if not key:
            continue
        if s.get("decision"):
            out["decisions"][key] = s["decision"]
        if s.get("proposal"):
            out["ai"][key] = s["proposal"]
        if s.get("read"):
            out["blind"][key] = s["read"]
        if s.get("evidence"):
            out["evidence"][key] = s["evidence"]
    return out


def import_legacy(assessments: dict, actor: str = "migration",
                  path: Path | None = None) -> list[str]:
    """One-off migration from the `assessments.json` blob.

    Every imported cycle is marked `imported: true` in its payload and its actor is
    `migration`, because a record reconstructed from a mutable file is not the same evidence as
    one written at the time it happened, and a replay should be able to exclude it.
    """
    made = []
    keys = set(assessments.get("decisions", {})) | set(assessments.get("ai", {})) \
        | set(assessments.get("blind", {}))
    for key in sorted(keys):
        control_id = str(key).split("|")[-1] if "|" in str(key) else str(key)
        cid = new_cycle_id(control_id)
        append("cycle_started", cycle_id=cid, actor=actor, control_id=control_id,
               payload={"imported": True, "legacy_key": key}, path=path)
        for src, kind, field in (("evidence", "evidence_bound", None),
                                 ("ai", "proposed", "proposal"),
                                 ("blind", "read", "read"),
                                 ("decisions", "decided", None)):
            val = (assessments.get(src) or {}).get(key)
            if val is None:
                continue
            pl = {field: val, "imported": True} if field else dict(val, imported=True)
            append(kind, cycle_id=cid, actor=actor, control_id=control_id, payload=pl, path=path)
        made.append(cid)
    return made
