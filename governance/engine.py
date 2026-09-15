"""GE-112..115 facade — one service boundary for the Streamlit consumer."""
from __future__ import annotations

from typing import Iterable

from governance.continuous_state import Finding, ObservationSchedule, transition
from governance.planner import VerificationPlan, build_plan
from governance.predicate_engine import ControlResult, evaluate
from governance.resources import Resource, ResourceSelector, select_resources
from governance.scheduler import ObservationJob, due_jobs


def plan(*, control_id: str, resources: Iterable[Resource], selector: ResourceSelector,
         available_capabilities: Iterable[str]) -> tuple[VerificationPlan, list[Resource]]:
    selected = select_resources(resources, selector)
    return build_plan(control_id=control_id, resources=[r.resource_id for r in selected],
                      available_capabilities=available_capabilities), selected


def evaluate_control(*, control_id: str, resource_id: str, observations, predicates,
                     contract_hash: str = "", policy_hash: str = "", exception_ref: str | None = None) -> ControlResult:
    return evaluate(control_id=control_id, resource_id=resource_id, observations=observations,
                    predicates=predicates, contract_hash=contract_hash, policy_hash=policy_hash,
                    exception_ref=exception_ref)


def advance_finding(finding: Finding | None, result: ControlResult, *, severity: str = "medium") -> Finding:
    return transition(finding, result, severity=severity)


__all__ = ["Finding", "ObservationSchedule", "ObservationJob", "Resource", "ResourceSelector", "plan",
           "evaluate_control", "advance_finding", "due_jobs"]
