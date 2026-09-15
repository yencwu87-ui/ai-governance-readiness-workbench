"""GE-114 — verification planning.

The planner answers how a requirement can be verified. It does not evaluate evidence and it never
produces compliance or sufficiency conclusions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import yaml

from governance.specs import control_predicate_specs

ROOT = Path(__file__).resolve().parent.parent
ELEMENT_TESTING = ROOT / "governance" / "knowledge" / "element_testing.yaml"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class VerificationRequirement:
    control_id: str
    element_id: str
    verification: str
    evidence_types: tuple[str, ...]
    capability_hints: tuple[str, ...]
    failure_condition: str


@dataclass(frozen=True)
class VerificationPlan:
    control_id: str
    resource_ids: tuple[str, ...]
    requirements: tuple[VerificationRequirement, ...]
    available_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    plan_hash: str = ""

    def __post_init__(self) -> None:
        if not self.plan_hash:
            object.__setattr__(self, "plan_hash", _sha({
                "control_id": self.control_id,
                "resource_ids": self.resource_ids,
                "requirements": [asdict(x) for x in self.requirements],
                "available_capabilities": self.available_capabilities,
                "missing_capabilities": self.missing_capabilities,
            }))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_element_testing() -> dict:
    if not ELEMENT_TESTING.exists():
        return {}
    return yaml.safe_load(ELEMENT_TESTING.read_text(encoding="utf-8")) or {}


def _requirements(control_id: str) -> list[VerificationRequirement]:
    data = load_element_testing()
    if data.get("control_id") != control_id:
        return []
    out = []
    for eid, spec in (data.get("elements") or {}).items():
        out.append(VerificationRequirement(
            control_id=control_id,
            element_id=str(eid),
            verification=str(spec.get("verification") or ""),
            evidence_types=tuple(str(x) for x in (spec.get("evidence_types") or [])),
            capability_hints=tuple(str(x) for x in (spec.get("capability_hints") or [])),
            failure_condition=str(spec.get("failure_condition") or ""),
        ))
    return out


def build_plan(*, control_id: str, resources: Iterable[str], available_capabilities: Iterable[str]) -> VerificationPlan:
    reqs = _requirements(control_id)
    available = tuple(sorted(set(str(x) for x in available_capabilities)))
    needed = sorted({cap for r in reqs for cap in r.capability_hints})
    missing = tuple(x for x in needed if x not in available)
    return VerificationPlan(control_id, tuple(str(x) for x in resources), tuple(reqs), available, tuple(missing))
