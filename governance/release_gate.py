"""Release gate for assessor evaluation results."""
from __future__ import annotations

DEFAULT_THRESHOLDS = {
    "accuracy_min": 0.80,
    "real_accuracy_min": 0.90,
    "adjacent_accuracy_min": 0.95,
    "over_credit_max": 0.05,
    "refusal_rate_max": 0.05,
    "quarantine_rate_max": 0.15,
    "baseline_margin_min": 0.10,
}


def evaluate_release_gate(summary: dict, thresholds: dict | None = None) -> dict:
    """Return PASS/FAIL/INCONCLUSIVE with explicit reasons.

    This is intentionally independent from the evaluator so the policy gate can be tested
    against stored result JSON without making another model call.
    """
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    checks = []

    if summary.get("status") == "NOT_TESTABLE":
        return {"status": "INCONCLUSIVE", "checks": [], "failed": ["evaluation status is NOT_TESTABLE"]}

    def check(name, value, op, limit):
        ok = value is not None and op(value, limit)
        checks.append({"name": name, "value": value, "limit": limit, "pass": ok})
        return ok

    check("accuracy", summary.get("accuracy"), lambda a, b: a >= b, t["accuracy_min"])
    check("real_accuracy", (summary.get("accuracy_by_kind") or {}).get("real", {}).get("accuracy"),
          lambda a, b: a >= b, t["real_accuracy_min"])
    check("adjacent_accuracy", summary.get("adjacent_accuracy"), lambda a, b: a >= b, t["adjacent_accuracy_min"])
    check("over_credit_rate", summary.get("over_credit_rate"), lambda a, b: a <= b, t["over_credit_max"])
    check("refusal_rate", summary.get("refusal_rate"), lambda a, b: a <= b, t["refusal_rate_max"])
    check("quarantine_rate", summary.get("quarantine_rate"), lambda a, b: a <= b, t["quarantine_rate_max"])
    check("baseline_margin", summary.get("baseline_margin"), lambda a, b: a >= b, t["baseline_margin_min"])
    if summary.get("real_full_cases") is not None:
        checks.append({"name":"real_full_cases","value":summary.get("real_full_cases"),"limit":3,"pass":summary.get("real_full_cases",0) >= 3})
    if "label_governance" in summary:
        lg = summary.get("label_governance") or {}
        checks.append({"name": "label_governance", "value": lg.get("status"), "limit": "PASS",
                       "pass": lg.get("status") == "PASS"})
        checks.append({"name": "label_distribution_ready", "value": lg.get("distribution_status"),
                       "limit": "PASS", "pass": lg.get("distribution_status") == "PASS"})

    failed = [c["name"] for c in checks if not c["pass"]]
    return {"status": "PASS" if not failed else "FAIL", "checks": checks, "failed": failed}
