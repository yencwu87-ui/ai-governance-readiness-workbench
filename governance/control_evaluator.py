"""Deterministic evaluation of a governed control's declared predicate specification."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Iterable

from governance.observation import Observation
from governance.predicate_engine import ControlResult, evaluate
from governance.specs import control_predicate_specs, predicate_spec_hash
from caa import checks

ELEMENT_STATUSES = {"PASS", "FAIL", "NOT_TESTABLE", "NOT_APPLICABLE", "STALE", "ERROR"}


@dataclass(frozen=True)
class ElementResult:
    element_id: str
    status: str
    predicate_results: tuple[dict[str, Any], ...] = ()
    applicability: str = "applicable"
    reason_codes: tuple[str, ...] = ()
    specification_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovernedControlResult:
    control_id: str
    resource_id: str
    status: str
    element_results: tuple[ElementResult, ...]
    contract_hash: str
    predicate_spec_hash: str
    observation_refs: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _applicable(observations: list[Observation], spec: dict[str, Any], evaluated_at: str | None) -> tuple[str, list[str]]:
    rule = spec.get("applicability")
    if not rule:
        return "applicable", []
    source = str(rule.get("source") or "")
    field = str(rule.get("field") or "")
    expected = rule.get("equals")
    ctx: dict[str, list[dict]] = {}
    for obs in observations:
        if "adapter_result" not in obs.payload:
            ctx.setdefault(obs.source, []).append(dict(obs.payload))
            if obs.provenance.get("source_name"):
                ctx.setdefault(str(obs.provenance["source_name"]), []).append(dict(obs.payload))
    recs = ctx.get(source)
    if recs is None:
        return "not_testable", ["APPLICABILITY_SOURCE_MISSING"]
    if not recs:
        return "not_testable", ["APPLICABILITY_NO_RECORDS"]
    values = [r.get(field) for r in recs]
    normalized = lambda v: str(v).strip().lower() if isinstance(v, str) else v
    matched = any(normalized(v) == normalized(expected) for v in values)
    if matched:
        return "applicable", []
    return "not_applicable", ["PRECONDITION_NOT_HELD"]


def _overall(statuses: list[str]) -> tuple[str, tuple[str, ...]]:
    scored = [s for s in statuses if s != "NOT_APPLICABLE"]
    if any(s == "ERROR" for s in scored):
        return "ERROR", ("ELEMENT_ERROR",)
    if any(s == "STALE" for s in scored):
        return "STALE", ("STALE_OBSERVATION",)
    if not scored:
        return "NOT_TESTABLE", ("NO_APPLICABLE_ELEMENTS",)
    if any(s == "FAIL" for s in scored):
        return "FAIL", ("ELEMENT_FAILURE",)
    if any(s == "NOT_TESTABLE" for s in scored):
        return "NOT_TESTABLE", ("ELEMENTS_NOT_TESTABLE",)
    return "PASS", ("ALL_APPLICABLE_ELEMENTS_PASS",)


def evaluate_governed_control(*, control_id: str, resource_id: str,
                              observations: Iterable[Observation], contract_hash: str,
                              framework: str = "",
                              policy_hash: str = "", evaluated_at: str | None = None,
                              exception_ref: str | None = None) -> GovernedControlResult:
    obs = list(observations)
    specs = control_predicate_specs(control_id, framework)
    spec_hash = predicate_spec_hash(control_id, framework)
    if not specs:
        return GovernedControlResult(control_id, resource_id, "NOT_TESTABLE", (), contract_hash,
                                     spec_hash, tuple(o.observation_id for o in obs),
                                     ("NO_PREDICATE_SPECIFICATION",), evaluated_at or "")
    if exception_ref:
        return GovernedControlResult(control_id, resource_id, "EXCEPTED", (), contract_hash,
                                     spec_hash, tuple(o.observation_id for o in obs),
                                     ("EXCEPTED",), evaluated_at or "")

    elements: list[ElementResult] = []
    for element_id, spec in sorted(specs.items()):
        if str(spec.get("observability")) == "out_of_band":
            continue
        applicability, reasons = _applicable(obs, spec, evaluated_at)
        if applicability == "not_applicable":
            elements.append(ElementResult(str(element_id), "NOT_APPLICABLE", (), applicability,
                                          tuple(reasons), spec_hash))
            continue
        if applicability == "not_testable":
            elements.append(ElementResult(str(element_id), "NOT_TESTABLE", (), applicability,
                                          tuple(reasons), spec_hash))
            continue
        result = evaluate(control_id=control_id, resource_id=resource_id, observations=obs,
                          predicates=spec.get("predicates") or [], contract_hash=contract_hash,
                          policy_hash=policy_hash, evaluated_at=evaluated_at)
        elements.append(ElementResult(str(element_id), result.status,
                                      tuple(x.to_dict() for x in result.predicate_results),
                                      applicability, tuple(result.reason_codes), spec_hash))

    status, reasons = _overall([e.status for e in elements])
    return GovernedControlResult(control_id, resource_id, status, tuple(elements), contract_hash,
                                 spec_hash, tuple(o.observation_id for o in obs), reasons,
                                 evaluated_at or "")
