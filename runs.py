"""WB-050 — the run.

The unit of work here has been the control. Puppet's unit is the run: the whole catalog,
evaluated at time T against manifest version V, producing one report. That difference is what
makes drift meaningful — without a run there is nothing for "since last time" to refer to.

A run in this system is deliberately cheap and deliberately model-free. It records three things
per control and calls nothing:

  catalog      what the control requires right now — the requirement version and the contract
               version. This is the yardstick, and a run that cannot say which yardstick it used
               cannot be compared to another run.
  evidence     a digest of the passages that currently match the control. Not the content, a
               hash: enough to tell that evidence changed, not enough to leak it into a log.
  outcome      the latest decision recorded for that control in the event store, or none.

No assessment happens. That is the point, and it is what makes nightly runs tractable: a run
detects *change*, and only changed controls need a model, a reviewer, or anyone's attention. A
system that re-assessed 195 controls every night would generate more findings per week than a
second-line team can decide on, and the backlog would become the product.

The catalog hash exists to keep drift honest. If the catalog changed between two runs, a
difference in outcome is not evidence that the estate moved — the yardstick moved. `drift.py`
refuses to attribute those to the control.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = Path(os.environ.get("WB_RUN_LOG", ROOT / "governance" / "runs.jsonl"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- catalog

def contract_sha(control_id: str, framework: str) -> str | None:
    """Hash of the control's governed contract — elements, boundary, requirement text."""
    try:
        from governance.control_contract import get_control_contract
        c = get_control_contract(control_id, framework) or {}
    except Exception:
        return None
    if not c:
        return None
    body = {k: c.get(k) for k in ("requirement", "elements", "boundary",
                                  "population_and_evidence_floor")}
    return _sha(json.dumps(body, sort_keys=True, default=str))


def requirement_sha(control_id: str) -> str | None:
    try:
        from eval_adapters import requirement_sha as rs
        return rs(control_id)
    except Exception:
        return None


def compile_catalog(controls) -> dict:
    """The yardstick, resolved and hashed.

    Named after Puppet's compiled catalog for the same reason: a run is only comparable to
    another run that was measured against the same thing.
    """
    entries = []
    for c in controls:
        entries.append({
            "control_id": c.id,
            "framework": c.lib,
            "requirement_sha": requirement_sha(c.id),
            "contract_sha": contract_sha(c.id, c.lib),
        })
    entries.sort(key=lambda e: (e["framework"], e["control_id"]))
    return {"controls": entries, "count": len(entries),
            "catalog_sha": _sha(json.dumps(entries, sort_keys=True))}


# ---------------------------------------------------------------- evidence state

def evidence_state(controls, folder: str, *, min_ratio: float | None = None) -> dict:
    """Per-control digest of the currently matching passages.

    Hashes, never content. A run log is read by more people than an evidence folder is, and a
    digest answers the only question drift asks — did this change — without carrying anything
    that would have to be handled as evidence itself.
    """
    from pipeline import index_folder, match_controls
    from scanner import MIN_RATIO
    idx, signals = index_folder(folder)
    matches = match_controls(idx, list(controls), min_ratio=min_ratio or MIN_RATIO)
    out = {}
    for c in controls:
        hits = matches.get(c.key) or []
        if not hits:
            out[c.id] = {"matched": 0, "digest": None, "sources": []}
            continue
        parts, sources = [], []
        for chunk, score in hits:
            parts.append(_sha(getattr(chunk, "text", "")))
            src = getattr(chunk, "path", "") or getattr(chunk, "label", "")
            if src and src not in sources:
                sources.append(src)
        out[c.id] = {"matched": len(hits), "digest": _sha("|".join(sorted(parts))),
                     "sources": sorted(sources)}
    return {"controls": out, "documents": len({getattr(ch, "path", "") for ch in idx.chunks}),
            "passages": len(idx.chunks), "signals": len(signals), "folder": folder,
            "min_ratio": min_ratio or MIN_RATIO}


# ---------------------------------------------------------------- outcome state

def outcome_state(control_ids: list[str]) -> dict:
    """The latest recorded decision per control, from the event store.

    A control with no decision is `None`, never a rating. An unassessed control and a control
    assessed as `none` are different facts and must not collapse into one another in a drift
    report — that collapse is how a coverage gap gets read as an adverse finding, or worse, how
    an adverse finding gets read as a coverage gap.
    """
    import events
    latest: dict[str, dict] = {}
    for s in events.iter_states():
        cid = s.get("control_id")
        if cid not in control_ids or s.get("stage") != "decided":
            continue
        prev = latest.get(cid)
        if prev is None or s["updated"] > prev["decided_at"]:
            d = s["decision"]
            latest[cid] = {"sufficiency": d.get("sufficiency"), "maturity": d.get("maturity"),
                           "reviewer": s.get("decided_by"), "decided_at": s["updated"],
                           "cycle_id": s["cycle_id"], "reason": d.get("reason", "")}
    return {cid: latest.get(cid) for cid in control_ids}


# ---------------------------------------------------------------- the run

def take(folder: str, controls, *, actor: str = "system", trigger: str = "manual",
         min_ratio: float | None = None, path: Path | None = None) -> dict:
    """Take a run. No model is called and nothing is assessed."""
    catalog = compile_catalog(controls)
    evidence = evidence_state(controls, folder, min_ratio=min_ratio)
    outcomes = outcome_state([c.id for c in controls])
    run = {
        "run_id": f"run-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
        "ts": _now(), "actor": actor, "trigger": trigger,
        "catalog_sha": catalog["catalog_sha"], "catalog": catalog["controls"],
        "evidence": evidence["controls"],
        "scan": {k: evidence[k] for k in ("documents", "passages", "signals", "folder", "min_ratio")},
        "outcomes": outcomes,
        "engine": "noop",   # this tool never remediates; a run observes and nothing else
    }
    p = Path(path or RUNS)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, default=str) + "\n")
    return run


def load_all(path: Path | None = None) -> list[dict]:
    p = Path(path or RUNS)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def get(run_id: str, path: Path | None = None) -> dict | None:
    for r in load_all(path):
        if r["run_id"] == run_id:
            return r
    return None


def latest(n: int = 1, path: Path | None = None) -> list[dict]:
    return load_all(path)[-n:]


def previous(run_id: str, path: Path | None = None) -> dict | None:
    runs = load_all(path)
    for i, r in enumerate(runs):
        if r["run_id"] == run_id:
            return runs[i - 1] if i > 0 else None
    return None
