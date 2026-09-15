"""GE-115 — pure observation scheduling queries; no background execution or remediation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from governance.continuous_state import ObservationSchedule

@dataclass(frozen=True)
class ObservationJob:
    job_id: str
    control_id: str
    resource_id: str
    schedule: ObservationSchedule
    capability: str

    def due(self, at: str | None = None) -> bool:
        return self.schedule.due(at)


def due_jobs(jobs: Iterable[ObservationJob], *, at: str | None = None) -> list[ObservationJob]:
    return [j for j in jobs if j.due(at)]
