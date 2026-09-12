"""Governance checks for the evaluator's labels and rubric.

This module treats labels as governed data, not merely test fixtures. It checks:
- class distribution for diagnostic evaluation sets
- label/rubric contradictions in authored cases
- one-line, evidence-grounded reviewer justifications
- basic metadata needed to audit who/when decided a label

It deliberately does not infer truth from the control text. Human-labelled evidence remains the
source of truth; these checks catch obvious contradictions and dataset-design defects.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

LEVELS = ("none", "partial", "full")
RANK = {"none": 0, "partial": 1, "full": 2}

OBVIOUS_FULL_CONTRADICTIONS = (
    ("stale", "full", "stale evidence should not be full"),
    ("evidence for a different control", "full", "wrong-control evidence should not be full"),
    ("vendor attestation instead of own control", "full", "third-party attestation should not be full for an own-control requirement"),
    ("refers to a document not supplied", "full", "missing referenced artefacts should not be full"),
    ("contradictory evidence", "full", "contradictory evidence requires a gap/ambiguity review before full"),
    ("embedded instruction", "full", "embedded instructions are not evidence and require caution"),
    ("aspirational", "full", "future/aspirational evidence should not be full"),
)

REASONALITY_MARKERS = (
    "confirm ", "inspect ", "test ", "review ", "reconcile ", "establish ",
    "need the ", "trace ", "check ", "look at ", "verify ",
)


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def distribution(cases: Iterable[dict], *, exclude_ambiguous: bool = True) -> dict[str, int]:
    out = Counter()
    for c in cases:
        label = c.get("label") or {}
        if exclude_ambiguous and label.get("ambiguous"):
            continue
        s = label.get("sufficiency")
        if s in LEVELS:
            out[s] += 1
    return {k: out.get(k, 0) for k in LEVELS}


def distribution_readiness(dist: dict[str, int], *, min_each: int = 5, max_share: float = 0.60) -> dict:
    n = sum(dist.values())
    missing = [k for k in LEVELS if dist.get(k, 0) < min_each]
    shares = {k: (dist.get(k, 0) / n if n else 0.0) for k in LEVELS}
    thin = min(shares.values(), default=0.0) < (min_each / n if n else 1.0)
    dominant = [k for k, share in shares.items() if share > max_share]
    return {
        "ready": not missing and not dominant,
        "min_each": min_each,
        "max_share": max_share,
        "missing_or_thin": missing,
        "dominant_classes": dominant,
        "n": n,
        "shares": {k: round(v, 3) for k, v in shares.items()},
        "min_share": round(min(shares.values(), default=0.0), 3),
        "max_observed_share": round(max(shares.values(), default=0.0), 3),
    }


def _reason_issues(case: dict) -> list[str]:
    label = case.get("label") or {}
    reason = str(label.get("reason") or "").strip()
    issues: list[str] = []
    if not reason or reason.strip().lower() in {"none", "n/a", "na"}:
        issues.append("missing reviewer justification")
        return issues
    # Reviewer justification should be a decision explanation, not a task list.
    if len(reason) > 220:
        issues.append("justification is not one-line/concise")
    lower = reason.lower()
    if any(lower.startswith(m) for m in REASONALITY_MARKERS):
        issues.append("justification reads like review instructions rather than the deciding fact")
    if reason.count(".") > 2:
        issues.append("justification contains multiple sentences; keep one deciding fact")
    return issues


def audit_case(case: dict) -> list[dict]:
    label = case.get("label") or {}
    suff = label.get("sufficiency")
    issues = []
    if suff not in LEVELS:
        issues.append("invalid sufficiency label")
    mat = label.get("maturity")
    if not isinstance(mat, int) or not 1 <= mat <= 5:
        issues.append("invalid maturity label")
    elif suff == "none" and mat > 1:
        issues.append("none cannot have maturity > 1")
    elif suff == "partial" and mat > 3:
        issues.append("partial cannot have maturity > 3")
    if not label.get("labelled_by"):
        issues.append("missing labelled_by")
    if not label.get("labelled_on"):
        issues.append("missing labelled_on")
    issues.extend(_reason_issues(case))

    note = str(case.get("note") or "").lower()
    for marker, bad_suff, msg in OBVIOUS_FULL_CONTRADICTIONS:
        if marker in note and suff == bad_suff:
            issues.append(msg)

    # Synthetic cases should have an explicit note because their truth is authored, not observed.
    if case.get("kind") == "synthetic" and not case.get("note"):
        issues.append("synthetic case missing scenario note")
    return [{"case_id": case.get("case_id"), "issue": i} for i in issues]


def audit(path: Path, *, min_each: int = 5) -> dict:
    cases = load_cases(path)
    dist = distribution(cases)
    readiness = distribution_readiness(dist, min_each=min_each)
    problems = [item for c in cases for item in audit_case(c)]
    return {
        "path": str(path),
        "case_count": len(cases),
        "label_distribution": dist,
        "distribution_readiness": readiness,
        "problem_count": len(problems),
        "problems": problems,
        "status": "PASS" if not problems else "FAIL",
        "distribution_status": "PASS" if readiness["ready"] else "NOT_READY",
    }


def print_report(report: dict) -> None:
    d = report["label_distribution"]
    r = report["distribution_readiness"]
    print(f"label distribution: none={d['none']} partial={d['partial']} full={d['full']}")
    print(f"diagnostic balance: {'READY' if r['ready'] else 'NOT_READY'} (min {r['min_each']} each)")
    if r["missing_or_thin"]:
        print("  thin classes:", ", ".join(r["missing_or_thin"]))
    if r.get("dominant_classes"):
        print("  dominant classes:", ", ".join(r["dominant_classes"]))
    if report["problems"]:
        print(f"label/rubric problems: {report['problem_count']}")
        for p in report["problems"]:
            print(f"  {p['case_id']}: {p['issue']}")
    print(f"label governance: {report['status']}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(Path(__file__).with_name("golden_set.jsonl")))
    ap.add_argument("--min-each", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = audit(Path(args.set), min_each=args.min_each)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
    raise SystemExit(0 if rep["status"] == "PASS" else 1)
