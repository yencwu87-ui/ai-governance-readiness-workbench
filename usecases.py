"""Use-case register — the unit of lifecycle assessment.

The 11 plays describe events in the life of ONE AI use case, so a play-step decision is
recorded per (use_case_id, step_id). The register lives in governance/usecases.csv and is
edited as text, like the other governance exports.

Columns: id, name, owner, materiality (low|medium|high|critical), status, notes
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path

REGISTER = Path(__file__).parent / "governance" / "usecases.csv"
FIELDS = ["id", "name", "owner", "materiality", "status", "notes"]
MATERIALITY = ("low", "medium", "high", "critical")


@dataclass
class UseCase:
    id: str
    name: str
    owner: str = ""
    materiality: str = "medium"
    status: str = "active"
    notes: str = ""


def load(path: Path = REGISTER) -> list[UseCase]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        r = {k: (r.get(k) or "").strip() for k in FIELDS}
        if not r["id"]:
            continue
        if r["materiality"] not in MATERIALITY:
            r["materiality"] = "medium"
        out.append(UseCase(**r))
    return out


def save(cases: list[UseCase], path: Path = REGISTER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for c in cases:
            w.writerow(asdict(c))


def get(uc_id: str, path: Path = REGISTER) -> UseCase | None:
    return next((c for c in load(path) if c.id == uc_id), None)
