"""WB-041 — one place where model choice and model behaviour are decided.

Before this there were three transports: `assessor._ollama`, `judge.call_ollama`, and the stress
targets, each with its own timeout, retry and temperature handling. Two consequences, both felt:

  The challenger could not have its own model. `challenge.py` imports `_ollama`, `_anthropic`,
  `PROVIDER` and `model_name` from `assessor` — six imports, four of them private — so the
  challenger *is* the assessor's transport. `WB_JUDGE_MODEL` exists for the step judge and there
  was no equivalent for the challenger, which is why running a small model for element verdicts
  and a larger one for challenges was awkward rather than a config change.

  Nothing was measured. When llama3.2 dropped 73% of element verdicts, the only way to find out
  was to write a probe. Latency, failure rate and JSON-parse failure rate per role are the
  numbers that would have shown it without one.

This module does not rewrite the existing callers. `model_for()` is a context manager that runs
an existing call under the role's model, and `observe()` records what happened. Migrating
`assessor` and `challenge` onto `call()` directly is a later step and a larger diff; this gets
per-role models and instrumentation today without touching a tested path.

Roles are named for the job, not the module, because two modules can do one job and one module
can do two — `assessor` does both `assess` and `elements`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = Path(os.environ.get("WB_LLM_METRICS", ROOT / "governance" / "llm_metrics.jsonl"))

ROLES = ("assess", "elements", "challenge", "challenge_claim_vet", "challenge_disagreement", "judge")

#: Per-role override, then the shared default, then the built-in. Every role can be pointed at
#: a different model without touching code — which is the whole point of the seam.
_ENV = {
    "assess": "WB_MODEL_ASSESS",
    "elements": "WB_MODEL_ELEMENTS",
    "challenge": "WB_MODEL_CHALLENGE",
    "challenge_claim_vet": "WB_MODEL_CHALLENGE",
    "challenge_disagreement": "WB_MODEL_CHALLENGE",
    "judge": "WB_JUDGE_MODEL",
}

DEFAULT = "llama3.1:8b"


def model_name(role: str) -> str:
    """The model this role should run on."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r} — roles are {', '.join(ROLES)}")
    return (os.environ.get(_ENV[role])
            or os.environ.get("OLLAMA_MODEL")
            or DEFAULT)


def roles_in_use() -> dict[str, str]:
    return {r: model_name(r) for r in ROLES}


@contextmanager
def model_for(role: str):
    """Run an existing assessor/judge call under this role's model.

    Sets the module-level model the legacy transports read, and restores it afterwards even if
    the call raises. Not thread-safe, and deliberately so — making it thread-safe would mean
    threading a config object through every call site, which is the migration this defers.
    """
    name = model_name(role)
    import assessor
    saved_assessor = getattr(assessor, "OLLAMA_MODEL", None)
    saved_judge = None
    try:
        import judge
        saved_judge = getattr(judge, "JUDGE_MODEL", None)
    except Exception:
        judge = None
    saved_role = os.environ.get("WB_ACTIVE_LLM_ROLE")
    try:
        assessor.OLLAMA_MODEL = name
        os.environ["WB_ACTIVE_LLM_ROLE"] = role
        if judge is not None:
            judge.JUDGE_MODEL = name
        yield name
    finally:
        if saved_assessor is not None:
            assessor.OLLAMA_MODEL = saved_assessor
        if judge is not None and saved_judge is not None:
            judge.JUDGE_MODEL = saved_judge
        if saved_role is None:
            os.environ.pop("WB_ACTIVE_LLM_ROLE", None)
        else:
            os.environ["WB_ACTIVE_LLM_ROLE"] = saved_role


@contextmanager
def observe(role: str, *, cycle_id: str = "", control_id: str = "", path: Path | None = None):
    """Time a model call and record the outcome, whether it succeeded or not.

    A failed call is recorded as a failure rather than dropped, for the same reason a failed
    assessment is an error rather than a rating of none: a call that did not happen must not be
    indistinguishable from one that happened and found nothing.
    """
    rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "role": role, "model": model_name(role), "cycle_id": cycle_id,
           "control_id": control_id, "ok": True, "error": None}
    started = time.monotonic()
    try:
        yield rec
    except Exception as e:
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        rec["ms"] = round((time.monotonic() - started) * 1000)
        p = Path(path or METRICS)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def summary(path: Path | None = None) -> dict:
    """Per-role latency and failure rate. The numbers a probe had to be written to get."""
    p = Path(path or METRICS)
    if not p.exists():
        return {"calls": 0, "by_role": {}}
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r.get("role", "?"), {"calls": 0, "failures": 0, "ms": [], "models": set()})
        b["calls"] += 1
        b["failures"] += not r.get("ok", True)
        if isinstance(r.get("ms"), (int, float)):
            b["ms"].append(r["ms"])
        b["models"].add(r.get("model", "?"))
    out = {}
    for role, b in by.items():
        ms = sorted(b["ms"])
        out[role] = {
            "calls": b["calls"],
            "failures": b["failures"],
            "failure_rate": round(b["failures"] / b["calls"], 3) if b["calls"] else None,
            "median_ms": ms[len(ms) // 2] if ms else None,
            "p90_ms": ms[int(len(ms) * 0.9)] if len(ms) >= 10 else None,
            "models": sorted(b["models"]),
        }
    return {"calls": len(rows), "by_role": out}
