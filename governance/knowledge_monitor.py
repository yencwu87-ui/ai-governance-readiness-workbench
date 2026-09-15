"""Runtime monitor for knowledge usage by assessor/challenge.

The monitor records retrieval facts, not model conclusions. It answers three separate questions:
1. Was local governed knowledge consulted and what was retrieved?
2. Was control-testing knowledge consulted?
3. Was live web knowledge attempted, and did it return findings that were injected into the prompt?

This is observability only. It never changes routing, evidence, ratings, or decisions.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("WB_KNOWLEDGE_MONITOR", ROOT / "governance" / "knowledge_usage.jsonl"))


def _write(row: dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def record(*, role: str, task: str, control_id: str, framework: str,
           local_memories: list[dict] | None = None,
           testing_rows: list[dict] | None = None,
           web_rows: list[dict] | None = None,
           web_attempted: bool = False,
           web_error: str | None = None,
           local_error: str | None = None,
           web_query: str = "",
           element_bundles: dict[str, dict] | None = None,
           retrieval_receipt: dict[str, Any] | None = None,
           triangulation: dict[str, Any] | None = None) -> dict[str, Any]:
    memories = local_memories or []
    testing = testing_rows or []
    web = web_rows or []
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "role": role,
        "task": task,
        "control_id": control_id,
        "framework": framework,
        "local": {
            "attempted": True,
            "findings": len(memories),
            "used": bool(memories),
            "memory_ids": [str(m.get("memory_id", "")) for m in memories if m.get("memory_id")],
            "error": local_error,
        },
        "control_testing": {
            "attempted": True,
            "findings": len(testing),
            "used": bool(testing),
            "controls": [str(r.get("control_id", "")) for r in testing if r.get("control_id")],
        },
        "internet": {
            "attempted": bool(web_attempted),
            "findings": len(web),
            "used": bool(web),
            "sources": [
                {"rank": int(i + 1), "title": str(r.get("title", "")), "url": str(r.get("url", ""))}
                for i, r in enumerate(web)
            ],
            "query": web_query,
            "error": web_error,
        },
    }
    if triangulation is not None:
        row["triangulation"] = {
            "status": triangulation.get("status"),
            "source_mapping_coverage": triangulation.get("source_mapping_coverage"),
            "future_change_signals": triangulation.get("future_change_signals", []),
            "insufficient_elements": triangulation.get("insufficient_elements", []),
        }
    if retrieval_receipt is not None:
        # Persist the receipt as observed retrieval fact.  It is intentionally not an
        # assessment result and does not include model reasoning.
        row["retrieval_receipt"] = retrieval_receipt
    bundles = element_bundles or {}
    row["elements"] = {
        str(eid): {
            "local_findings": len(item.get("local") or []),
            "testing_findings": len(item.get("testing") or []),
            "internet_findings": len(item.get("internet") or []),
        } for eid, item in bundles.items()
    }
    row["channels_used"] = [
        x for x, used in (
            ("local", bool(memories)),
            ("control_testing", bool(testing)),
            ("internet", bool(web)),
        ) if used
    ]
    row["internet_findings_used"] = bool(web)
    _write(row)
    return row


def read(limit: int = 200) -> list[dict[str, Any]]:
    if not LOG.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return rows[-max(1, int(limit)):]


def latest(*, control_id: str | None = None, role: str | None = None) -> dict[str, Any] | None:
    rows = read(500)
    for row in reversed(rows):
        if control_id and row.get("control_id") != control_id:
            continue
        if role and row.get("role") != role:
            continue
        return row
    return None


def summary(limit: int = 500) -> dict[str, Any]:
    rows = read(limit)
    out = {
        "runs": len(rows),
        "local_runs": sum(bool((r.get("local") or {}).get("used")) for r in rows),
        "testing_runs": sum(bool((r.get("control_testing") or {}).get("used")) for r in rows),
        "internet_attempts": sum(bool((r.get("internet") or {}).get("attempted")) for r in rows),
        "internet_findings": sum(bool((r.get("internet") or {}).get("used")) for r in rows),
        "internet_degraded": sum(bool((r.get("internet") or {}).get("error")) for r in rows),
        "by_role": {},
        "element_scoped_runs": sum(bool(r.get("elements")) for r in rows),
        "element_local_findings": sum(sum(int(v.get("local_findings", 0)) for v in (r.get("elements") or {}).values()) for r in rows),
        "element_testing_findings": sum(sum(int(v.get("testing_findings", 0)) for v in (r.get("elements") or {}).values()) for r in rows),
        "element_internet_findings": sum(sum(int(v.get("internet_findings", 0)) for v in (r.get("elements") or {}).values()) for r in rows),
    }
    for row in rows:
        role = str(row.get("role") or "?")
        b = out["by_role"].setdefault(role, {"runs": 0, "local": 0, "testing": 0, "internet": 0})
        b["runs"] += 1
        b["local"] += bool((row.get("local") or {}).get("used"))
        b["testing"] += bool((row.get("control_testing") or {}).get("used"))
        b["internet"] += bool((row.get("internet") or {}).get("used"))
    return out
