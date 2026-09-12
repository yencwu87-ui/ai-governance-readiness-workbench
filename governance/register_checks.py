"""Integrity checks for the change-ticket register used as governance evidence."""
from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

TICKET_RE = re.compile(r"^WB-\d{3}$")
REQUIRED = {"ticket_id", "model_id", "version", "risk_tier", "approver", "emergency", "opened_at", "approved_at", "description"}


def load_tickets(path: Path | str) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def referenced_ticket_ids(root: Path | str) -> set[str]:
    """Find WB-### references in text/config files, excluding generated caches."""
    root = Path(root)
    found: set[str] = set()
    excluded_dirs = {".git", "__pycache__", ".pytest_cache", "docs", "examples", "sample_evidence", "evidence", "graphify-out", "eval", "stress"}
    for p in root.rglob("*"):
        if not p.is_file() or any(part in excluded_dirs for part in p.parts) or p.suffix in {".pyc", ".xlsx"}:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update(re.findall(r"\bWB-\d{3}\b", text))
    return found


def validate_ticket_register(path: Path | str, *, root: Path | str | None = None) -> dict:
    """Return errors/warnings without mutating the register."""
    p = Path(path)
    rows = load_tickets(p)
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        errors.append("ticket register is empty")
        return {"errors": errors, "warnings": warnings, "count": 0, "ticket_ids": []}

    missing_columns = sorted(REQUIRED - set(rows[0]))
    if missing_columns:
        errors.append(f"missing columns: {', '.join(missing_columns)}")
        return {"errors": errors, "warnings": warnings, "count": len(rows), "ticket_ids": []}

    ids = [r.get("ticket_id", "").strip() for r in rows]
    for tid, n in Counter(ids).items():
        if not tid:
            errors.append("blank ticket_id")
        elif not TICKET_RE.fullmatch(tid):
            errors.append(f"invalid ticket_id {tid!r}")
        elif n > 1:
            errors.append(f"duplicate ticket_id {tid} ({n} rows)")

    for i, r in enumerate(rows, 2):
        status = str(r.get("record_status", "approved_record")).strip().lower()
        if not r.get("description", "").strip():
            errors.append(f"row {i} {r.get('ticket_id')}: missing description")
        try:
            opened = date.fromisoformat(r["opened_at"])
        except (ValueError, TypeError, KeyError):
            errors.append(f"row {i} {r.get('ticket_id')}: invalid opened_at")
            opened = None
        if status == "historical_reconstructed":
            warnings.append(f"row {i} {r.get('ticket_id')}: historical record reconstructed from repository evidence; approval metadata not verified")
        else:
            if not r.get("approver", "").strip():
                errors.append(f"row {i} {r.get('ticket_id')}: missing approver")
            try:
                approved = date.fromisoformat(r["approved_at"])
                if opened and approved < opened:
                    errors.append(f"row {i} {r.get('ticket_id')}: approved_at before opened_at")
            except (ValueError, TypeError, KeyError):
                errors.append(f"row {i} {r.get('ticket_id')}: invalid approved_at")

    if root is not None:
        refs = referenced_ticket_ids(root)
        registered = set(x for x in ids if x)
        missing = sorted(refs - registered)
        if missing:
            errors.append("referenced tickets absent from register: " + ", ".join(missing))

    return {"errors": errors, "warnings": warnings, "count": len(rows), "ticket_ids": sorted(set(ids))}
