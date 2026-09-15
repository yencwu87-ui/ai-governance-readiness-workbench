"""GE-112 — deterministic predicate evaluation over canonical Observations.

Predicates answer a governed question about facts. They never create facts and never infer
freshness. The existing deterministic CAA check registry is reused as the predicate library;
this module supplies the engine-level result object and the freshness/error/exception boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from caa import checks
from governance.observation import Observation

SCHEMA = "ge112.control_result.1"
STATUSES = {"PASS", "FAIL", "STALE", "NOT_TESTABLE", "ERROR", "EXCEPTED"}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PredicateResult:
    predicate: str
    status: str
    detail: str
    findings: list[dict] = field(default_factory=list)
    examined: int = 0
    in_scope: int = 0
    observation_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlResult:
    control_id: str
    resource_id: str
    status: str
    predicate_results: list[PredicateResult]
    observation_refs: list[str]
    reason_codes: list[str]
    evaluated_at: str
    stale_observation_refs: list[str]
    contract_hash: str = ""
    policy_hash: str = ""
    exception_ref: str | None = None
    integrity_hash: str = ""
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown ControlResult status {self.status!r}")
        if not self.integrity_hash:
            body = asdict(self)
            body["integrity_hash"] = ""
            object.__setattr__(self, "integrity_hash", _sha(body))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _context(observations: list[Observation]) -> dict[str, list[dict]]:
    ctx: dict[str, list[dict]] = {}
    for o in observations:
        # Run envelopes are facts about the provider run, but are not source records themselves.
        if "adapter_result" in o.payload:
            continue
        ctx.setdefault(o.source, []).append(dict(o.payload))
        ctx.setdefault(o.provenance.get("source_name", ""), []).append(dict(o.payload))
    return {k: v for k, v in ctx.items() if k}


def _sources_for(params: dict[str, Any]) -> set[str]:
    out = set()
    for key in ("source",):
        if params.get(key):
            out.add(str(params[key]))
    for side in ("left", "right", "subset", "superset"):
        side_cfg = params.get(side) or {}
        if isinstance(side_cfg, dict) and side_cfg.get("source"):
            out.add(str(side_cfg["source"]))
    return out


def evaluate(*, control_id: str, resource_id: str, observations: Iterable[Observation],
             predicates: Iterable[dict[str, Any]], contract_hash: str = "",
             policy_hash: str = "", evaluated_at: str | None = None,
             exception_ref: str | None = None) -> ControlResult:
    obs = list(observations)
    when = evaluated_at or _now()
    refs = [o.observation_id for o in obs]
    stale_refs = [o.observation_id for o in obs if o.freshness_known and o.is_stale(when)]

    if exception_ref:
        return ControlResult(control_id, resource_id, "EXCEPTED", [], refs, ["EXCEPTED"], when,
                             stale_refs, contract_hash, policy_hash, exception_ref)
    if not obs:
        return ControlResult(control_id, resource_id, "NOT_TESTABLE", [], [], ["NO_OBSERVATIONS"], when,
                             [], contract_hash, policy_hash)

    ctx = _context(obs)
    results: list[PredicateResult] = []
    for spec in predicates:
        name = str(spec.get("name") or spec.get("predicate") or "").strip()
        params = dict(spec.get("params") or {})
        if not name:
            results.append(PredicateResult("", "ERROR", "predicate name is required"))
            continue
        fn = checks.REGISTRY.get(name)
        needed_sources = _sources_for(params)
        relevant_stale = [o.observation_id for o in obs if o.observation_id in stale_refs and
                          (not needed_sources or o.source in needed_sources or
                           o.provenance.get("source_name") in needed_sources)]
        if relevant_stale:
            results.append(PredicateResult(name, "STALE", "required observation(s) are stale",
                                           observation_refs=relevant_stale))
            continue
        if fn is None:
            results.append(PredicateResult(name, "ERROR", f"unknown predicate: {name}"))
            continue
        try:
            r = fn(ctx, params)
            if r.verdict not in {"PASS", "FAIL", "NOT_TESTABLE"}:
                results.append(PredicateResult(name, "ERROR", f"invalid predicate verdict: {r.verdict}"))
            else:
                results.append(PredicateResult(name, r.verdict, r.detail, list(r.findings),
                                               r.examined, r.in_scope, refs))
        except Exception as exc:  # predicates are engine components; failure is a governed result
            results.append(PredicateResult(name, "ERROR", f"{type(exc).__name__}: {exc}"))

    statuses = [r.status for r in results]
    if any(s == "ERROR" for s in statuses):
        status = "ERROR"
        reasons = ["PREDICATE_ERROR"]
    elif any(s == "STALE" for s in statuses):
        status = "STALE"
        reasons = ["STALE_OBSERVATION"]
    elif not results or all(s == "NOT_TESTABLE" for s in statuses):
        status = "NOT_TESTABLE"
        reasons = ["PREDICATES_NOT_TESTABLE"]
    elif any(s == "FAIL" for s in statuses):
        status = "FAIL"
        reasons = ["PREDICATE_FAILURE"]
    else:
        status = "PASS"
        reasons = ["ALL_PREDICATES_PASS"]

    return ControlResult(control_id, resource_id, status, results, refs, reasons, when, stale_refs,
                         contract_hash, policy_hash)
