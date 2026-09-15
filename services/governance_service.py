"""GE-116 service facade: UI orchestration over the governed engine."""
from __future__ import annotations

from typing import Iterable
import hashlib
import json

from governance.control_evaluator import GovernedControlResult, evaluate_governed_control
from governance.engine import plan
from governance.observation import Observation
from governance.resources import Resource, ResourceSelector

# UI imports this as the service-owned resource constructor; governance semantics stay here.


def verification_plan(*, control_id: str, resources: Iterable[Resource], selector: ResourceSelector,
                      available_capabilities: Iterable[str]):
    return plan(control_id=control_id, resources=resources, selector=selector,
                available_capabilities=available_capabilities)


def contract_hash(control) -> str:
    payload = {
        "library": control.lib,
        "id": control.id,
        "title": control.title,
        "requirement": control.req,
        "elements": list(control.elements or ()),
        "boundary": dict(control.boundary or {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def deterministic_evaluate(*, control, resource_id: str, observations: Iterable[Observation],
                           policy_hash: str = "", evaluated_at: str | None = None,
                           exception_ref: str | None = None) -> GovernedControlResult:
    return evaluate_governed_control(
        control_id=control.id,
        framework=control.lib,
        resource_id=resource_id,
        observations=observations,
        contract_hash=contract_hash(control),
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        exception_ref=exception_ref,
    )
