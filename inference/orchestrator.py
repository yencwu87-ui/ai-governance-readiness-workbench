from __future__ import annotations

import json
import os
import time
import uuid
from typing import Callable, Any

from llm.client import model_for, observe
from .policy import TaskSignals, InferencePlan, build_plan
from .telemetry import record_task


def _call_legacy_ollama(system: str, user: str) -> str:
    import assessor
    return assessor._ollama(system, user)


def run_with_escalation(*, role: str, system: str, user: str,
                        signals: TaskSignals,
                        validate: Callable[[str], tuple[bool, str]] | None = None,
                        control_id: str = "", task_id: str = "",
                        invoke: Callable[[str, str], str] | None = None) -> tuple[str, InferencePlan, dict]:
    """Run one inference task, re-running once at a stronger tier when validation fails.

    The validator is deterministic whenever possible. No retry may turn a failed output into a
    governance decision; callers still run their existing domain validators afterwards.
    """
    task_id = task_id or f"INF-{uuid.uuid4().hex[:12]}"
    first = build_plan(signals)
    calls = 0
    failures = 0
    escalated = False
    started = time.monotonic()
    last_error = ""
    raw = ""

    tiers = [first]
    if first.tier != "critical" and (first.max_attempts > 1):
        second_signals = TaskSignals(**{**signals.__dict__, "prior_failures": signals.prior_failures + 1})
        second = build_plan(second_signals)
        if second.tier != first.tier or second.model != first.model:
            tiers.append(second)

    for idx, plan in enumerate(tiers):
        if idx > 0:
            escalated = True
        try:
            # The fallback flag is process-local and restored immediately. This module already
            # uses the legacy module-level model transport, so keeping the flag in the same narrow
            # window prevents an unrelated role from inheriting challenger fallback behaviour.
            old_fallback = os.environ.get("WB_INFERENCE_FALLBACK")
            if idx > 0 and role.startswith("challenge"):
                os.environ["WB_INFERENCE_FALLBACK"] = "1"
            try:
                with model_for(role):
                    # The legacy transport reads the model from assessor. When a plan specifies an
                    # escalation model, temporarily override that setting around the call.
                    import assessor
                    saved = assessor.OLLAMA_MODEL
                    assessor.OLLAMA_MODEL = plan.model
                    try:
                        with observe(role, cycle_id=task_id, control_id=control_id):
                            raw = (invoke or _call_legacy_ollama)(system, user)
                    finally:
                        assessor.OLLAMA_MODEL = saved
            finally:
                if old_fallback is None:
                    os.environ.pop("WB_INFERENCE_FALLBACK", None)
                else:
                    os.environ["WB_INFERENCE_FALLBACK"] = old_fallback
            calls += 1
        except Exception as exc:
            calls += 1
            failures += 1
            last_error = f"{type(exc).__name__}: {exc}"
            if idx == len(tiers) - 1:
                elapsed = round((time.monotonic() - started) * 1000)
                record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                            calls=calls, escalated=escalated, validation_failures=failures,
                            completed=False, elapsed_ms=elapsed, extra={"error": last_error})
                raise
            continue

        if validate is None:
            elapsed = round((time.monotonic() - started) * 1000)
            rec = record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                              calls=calls, escalated=escalated, validation_failures=failures,
                              completed=True, elapsed_ms=elapsed)
            return raw, plan, rec

        ok, reason = validate(raw)
        if ok:
            elapsed = round((time.monotonic() - started) * 1000)
            rec = record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                              calls=calls, escalated=escalated, validation_failures=failures,
                              completed=True, elapsed_ms=elapsed)
            return raw, plan, rec
        failures += 1
        last_error = reason

    elapsed = round((time.monotonic() - started) * 1000)
    record_task(task_id=task_id, role=role, control_id=control_id, plan=tiers[-1],
                calls=calls, escalated=escalated, validation_failures=failures,
                completed=False, elapsed_ms=elapsed, extra={"error": last_error})
    raise RuntimeError(last_error or "inference quality gate failed")
