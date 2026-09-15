from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
TASK_METRICS = Path(os.environ.get("WB_INFERENCE_TASK_METRICS", ROOT / "governance" / "inference_tasks.jsonl"))


def record_task(*, task_id: str, role: str, control_id: str, plan, calls: int,
                escalated: bool, validation_failures: int, completed: bool,
                elapsed_ms: int, extra: dict | None = None) -> dict:
    rec = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "task_id": task_id,
        "role": role,
        "control_id": control_id,
        "tier": plan.tier,
        "model": plan.model,
        "calls": calls,
        "escalated": bool(escalated),
        "validation_failures": validation_failures,
        "completed": bool(completed),
        "elapsed_ms": elapsed_ms,
        "reasons": list(plan.reasons),
    }
    if extra:
        rec.update(extra)
    p = Path(TASK_METRICS)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return rec
