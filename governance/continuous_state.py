"""GE-115 — temporal findings and observation scheduling.

This module changes state only from explicit ControlResults. It does not remediate resources and
it does not schedule side effects; `due()` is a pure query for a higher-level runner.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

STATES = {"UNKNOWN", "ADEQUATE", "DEGRADED", "NON_COMPLIANT", "RECOVERED", "STALE", "NOT_TESTABLE", "EXCEPTED"}


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Finding:
    finding_id: str
    control_id: str
    resource_id: str
    state: str
    first_seen: str
    last_seen: str
    severity: str = "medium"
    reason_codes: tuple[str, ...] = ()
    control_result_id: str = ""
    observation_refs: tuple[str, ...] = ()
    previous_state: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state_for(result_status: str, previous: str) -> str:
    return {
        "PASS": "RECOVERED" if previous in {"NON_COMPLIANT", "DEGRADED", "STALE"} else "ADEQUATE",
        "FAIL": "NON_COMPLIANT",
        "STALE": "STALE",
        "NOT_TESTABLE": "NOT_TESTABLE",
        "EXCEPTED": "EXCEPTED",
        "ERROR": "DEGRADED",
    }.get(result_status, "UNKNOWN")


def transition(finding: Finding | None, result: Any, *, severity: str = "medium",
               observed_at: str | None = None) -> Finding:
    when = observed_at or result.evaluated_at
    previous = finding.state if finding else "UNKNOWN"
    return Finding(
        finding_id=(finding.finding_id if finding else f"F-{result.control_id}-{result.resource_id}"),
        control_id=result.control_id,
        resource_id=result.resource_id,
        state=_state_for(result.status, previous),
        first_seen=(finding.first_seen if finding else when),
        last_seen=when,
        severity=severity,
        reason_codes=tuple(result.reason_codes),
        control_result_id=result.integrity_hash[:16],
        observation_refs=tuple(result.observation_refs),
        previous_state=previous,
    )


@dataclass(frozen=True)
class ObservationSchedule:
    cadence: timedelta
    next_due: str

    def due(self, at: str | None = None) -> bool:
        now = _dt(at) if at else datetime.now(timezone.utc)
        return now >= _dt(self.next_due)

    def advance(self, *, from_time: str | None = None) -> "ObservationSchedule":
        base = _dt(from_time) if from_time else _dt(self.next_due)
        return ObservationSchedule(self.cadence, (base + self.cadence).isoformat(timespec="seconds"))
