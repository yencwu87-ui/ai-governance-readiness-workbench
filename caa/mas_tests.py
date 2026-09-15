"""Executable MAS control tests driven by the v0.4 MAS test catalog.

The runner uses a normalized evidence contract and never invents evidence. Missing or
unavailable evidence is NOT_TESTABLE; observed failures are FAIL.

Evidence contract:
{
  "artefacts": [{"name": "AI inventory", "text": "...", "ref": "..."}],
  "records": {"inventory": [{...}], "changes": [{...}], ...}
}
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import argparse
import json
import math
import re


@dataclass
class MASCheckResult:
    control_id: str
    test_type: str
    verdict: str  # PASS | FAIL | NOT_TESTABLE
    detail: str
    findings: list[str]
    examined: int = 0
    in_scope: int = 0
    test_id: str = ""


@dataclass(frozen=True)
class MastTestSpec:
    control_id: str
    title: str
    design_test_id: str
    design_required_terms: tuple[str, ...]
    operating_test_id: str
    operating_sources: tuple[str, ...]
    operating_required_fields: tuple[str, ...] = ()
    operating_min_records: int = 1
    design_min_hits: int = 1
    unique_fields: tuple[str, ...] = ()
    ordering_pairs: tuple[tuple[str, str], ...] = ()


# The executable catalog is deliberately conservative.  It translates the approved v0.4
# ToD/ToE procedures into machine-checkable evidence floors/field checks.  Control-specific
# judgement remains a human gate.
SPECS: dict[str, MastTestSpec] = {
    "M1.1": MastTestSpec("M1.1", "Board & senior management accountability for AI risk", "MAS-M1.1-D", ("Board", "risk appetite", "accountab"), "MAS-M1.1-O", ("risk_reporting", "committee_minutes", "approvals")),
    "M1.2": MastTestSpec("M1.2", "AI policies & guiding principles", "MAS-M1.2-D", ("fair", "ethical", "accountab", "transparent"), "MAS-M1.2-O", ("ai_use_cases",), ("use_case_id", "policy_version")),
    "M1.3": MastTestSpec("M1.3", "Cross-functional AI oversight forum", "MAS-M1.3-D", ("terms of reference", "quorum", "decision rights"), "MAS-M1.3-O", ("committee_minutes",), ("meeting_date", "quorum", "decisions"), 3),
    "M1.4": MastTestSpec("M1.4", "AI risk appetite & risk tolerance", "MAS-M1.4-D", ("risk appetite", "threshold", "escalation"), "MAS-M1.4-O", ("risk_assessments", "incidents")),
    "M1.5": MastTestSpec("M1.5", "AI literacy, culture & training", "MAS-M1.5-D", ("competenc", "training", "refresher", "remediation"), "MAS-M1.5-O", ("training_records",), ("person_id", "course", "completed_at")),
    "M2.1": MastTestSpec("M2.1", "Consistent identification of where AI is used", "MAS-M2.1-D", ("AI use case", "intake", "triage", "unregistered"), "MAS-M2.1-O", ("ai_intake", "projects", "deployments")),
    "M2.2": MastTestSpec("M2.2", "AI inventory", "MAS-M2.2-D", ("inventory", "version", "use case", "owner", "lifecycle"), "MAS-M2.2-O", ("ai_inventory", "production_systems"), ("system_id", "version", "use_case", "owner"), unique_fields=("system_id",)),
    "M2.3": MastTestSpec("M2.3", "Risk materiality assessment", "MAS-M2.3-D", ("materiality", "impact", "complexity", "reliance", "inherent", "residual"), "MAS-M2.3-O", ("risk_assessments",), ("use_case_id", "inherent_risk", "residual_risk", "materiality")),
    "M2.4": MastTestSpec("M2.4", "AI risk identification & assessment across the lifecycle", "MAS-M2.4-D", ("lifecycle", "risk register", "risk owner", "inherent", "residual"), "MAS-M2.4-O", ("lifecycle_risk_register",), ("system_id", "lifecycle_stage", "risk", "owner", "residual_risk")),
    "M3.1": MastTestSpec("M3.1", "Data management, quality, representativeness & provenance", "MAS-M3.1-D", ("data management", "lineage", "quality", "provenance", "representat"), "MAS-M3.1-O", ("data_lineage", "data_quality"), ("dataset_id", "lineage", "quality_result")),
    "M3.2": MastTestSpec("M3.2", "Fairness & bias mitigation", "MAS-M3.2-D", ("fairness", "bias", "threshold", "mitigation", "affected group"), "MAS-M3.2-O", ("fairness_results",), ("use_case_id", "metric", "threshold", "result")),
    "M3.3": MastTestSpec("M3.3", "Transparency & explainability of AI outputs", "MAS-M3.3-D", ("transparency", "explainab", "model card", "stakeholder"), "MAS-M3.3-O", ("model_cards", "disclosures"), ("system_id", "version")),
    "M3.4": MastTestSpec("M3.4", "Human oversight & intervention", "MAS-M3.4-D", ("human oversight", "decision rights", "rollback", "intervention"), "MAS-M3.4-O", ("human_decisions", "overrides"), ("decision_id", "reviewer", "decision"), unique_fields=("decision_id",)),
    "M3.5": MastTestSpec("M3.5", "Model & feature selection", "MAS-M3.5-D", ("model selection", "feature", "rationale", "approval"), "MAS-M3.5-O", ("selection_records",), ("model_id", "rationale", "approval")),
    "M3.6": MastTestSpec("M3.6", "Evaluation, testing & independent validation", "MAS-M3.6-D", ("evaluation", "acceptance criteria", "independent validation", "testing"), "MAS-M3.6-O", ("validation_packages", "test_results"), ("system_id", "test_type", "result", "validator")),
    "M3.7": MastTestSpec("M3.7", "Technology & cybersecurity controls", "MAS-M3.7-D", ("security architecture", "threat model", "secure development", "penetration"), "MAS-M3.7-O", ("security_tests", "vulnerability_records"), ("system_id", "test_type", "result")),
    "M3.8": MastTestSpec("M3.8", "Reproducibility, auditability, logging & audit trails", "MAS-M3.8-D", ("logging", "audit trail", "reproducib", "traceab"), "MAS-M3.8-O", ("audit_logs", "decision_logs", "change_logs"), ("event_id", "timestamp", "actor"), unique_fields=("event_id",)),
    "M3.9": MastTestSpec("M3.9", "Pre-deployment review & approval", "MAS-M3.9-D", ("release gate", "pre-deploy", "acceptance criteria", "approval"), "MAS-M3.9-O", ("releases", "release_approvals"), ("release_id", "approved_at", "deployed_at"), unique_fields=("release_id",), ordering_pairs=(("approved_at", "deployed_at"),)),
    "M3.10": MastTestSpec("M3.10", "Post-deployment monitoring", "MAS-M3.10-D", ("monitoring", "drift", "dashboard", "revalidation", "backtesting"), "MAS-M3.10-O", ("monitoring_results",), ("system_id", "metric", "threshold", "observed_at")),
    "M3.11": MastTestSpec("M3.11", "Incident management & escalation", "MAS-M3.11-D", ("incident", "severity", "escalation", "notification"), "MAS-M3.11-O", ("ai_incidents",), ("incident_id", "severity", "detected_at", "escalated_at"), unique_fields=("incident_id",), ordering_pairs=(("detected_at", "escalated_at"),)),
    "M3.12": MastTestSpec("M3.12", "Change management", "MAS-M3.12-D", ("change management", "change taxonomy", "approval", "emergency change", "verification"), "MAS-M3.12-O", ("changes",), ("ticket_id", "approved_at", "implemented_at", "verified_at"), unique_fields=("ticket_id",), ordering_pairs=(("approved_at", "implemented_at"), ("implemented_at", "verified_at"))),
    "M3.13": MastTestSpec("M3.13", "Decommissioning / safe phase-out", "MAS-M3.13-D", ("decommission", "phase-out", "data disposal", "inventory"), "MAS-M3.13-O", ("retirements",), ("system_id", "retired_at", "inventory_status"), unique_fields=("system_id",)),
    "M3.14": MastTestSpec("M3.14", "Third-party / vendor AI risk management", "MAS-M3.14-D", ("vendor", "due diligence", "contract", "audit rights", "exit"), "MAS-M3.14-O", ("vendors", "vendor_reviews"), ("vendor_id", "due_diligence", "contract_status")),
    "M3.15": MastTestSpec("M3.15", "Generative AI & AI-agent risks", "MAS-M3.15-D", ("hallucination", "autonomy", "prompt injection", "data leakage", "red-team", "human oversight"), "MAS-M3.15-O", ("genai_risk_assessments", "red_team_tests"), ("system_id", "risk", "test_result")),
    "M4.1": MastTestSpec("M4.1", "Skills, training, resourcing & competency", "MAS-M4.1-D", ("competenc", "resourcing", "skills", "training", "succession"), "MAS-M4.1-O", ("role_assignments", "competency_records"), ("role", "person_id", "competency_status")),
    "M4.2": MastTestSpec("M4.2", "Technology infrastructure & tooling capacity", "MAS-M4.2-D", ("infrastructure", "capacity", "resilience", "scaling", "continuity"), "MAS-M4.2-O", ("capacity_metrics", "incidents", "recovery_tests"), ("service", "metric", "threshold", "observed_at")),
    "F1": MastTestSpec("F1", "Fairness", "MAS-F1-D", ("fairness", "affected groups", "threshold", "mitigation"), "MAS-F1-O", ("fairness_results",), ("use_case_id", "metric", "threshold", "result")),
    "F2": MastTestSpec("F2", "Ethics", "MAS-F2-D", ("ethical", "prohibited use", "attestation", "escalation"), "MAS-F2-O", ("ethics_assessments",), ("use_case_id", "attestation", "decision")),
    "F3": MastTestSpec("F3", "Accountability", "MAS-F3-D", ("accountab", "business owner", "model owner", "third-party", "non-delegable"), "MAS-F3-O", ("ai_decisions", "vendor_arrangements"), ("decision_id", "accountable_owner", "approval")),
    "F4": MastTestSpec("F4", "Transparency", "MAS-F4-D", ("transparency", "model card", "customer", "disclosure", "explanation"), "MAS-F4-O", ("live_systems", "disclosures"), ("system_id", "version", "disclosure_status")),
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _flatten_text(v: Any) -> str:
    if isinstance(v, dict):
        return " ".join(_flatten_text(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return " ".join(_flatten_text(x) for x in v)
    return str(v or "")


def _parse_dt(value: Any):
    if value in (None, ""):
        return None
    from datetime import datetime
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _find_term(text: str, term: str) -> bool:
    t = _norm(text)
    q = _norm(term)
    return bool(q) and q in t


def run_design(control_id: str, evidence: dict) -> MASCheckResult:
    spec = SPECS[control_id]
    arts = evidence.get("artefacts") or []
    text = _flatten_text(arts)
    if not arts:
        return MASCheckResult(control_id, "design", "NOT_TESTABLE", "No design artefacts supplied", ["design evidence unavailable"], test_id=spec.design_test_id)
    hits = [t for t in spec.design_required_terms if _find_term(text, t)]
    required_hits = max(spec.design_min_hits, math.ceil(len(spec.design_required_terms) * 0.60))
    if len(hits) < required_hits:
        return MASCheckResult(control_id, "design", "FAIL", f"Only {len(hits)}/{len(spec.design_required_terms)} design evidence markers found; minimum is {required_hits}", [f"missing evidence marker: {t}" for t in spec.design_required_terms if t not in hits], test_id=spec.design_test_id)
    return MASCheckResult(control_id, "design", "PASS", f"Design evidence contains {len(hits)}/{len(spec.design_required_terms)} expected markers", [], examined=len(arts), in_scope=len(arts), test_id=spec.design_test_id)


def run_operating(control_id: str, evidence: dict) -> MASCheckResult:
    spec = SPECS[control_id]
    records = evidence.get("records") or {}
    present = [(s, records.get(s) or []) for s in spec.operating_sources if records.get(s)]
    if not present:
        return MASCheckResult(control_id, "operating", "NOT_TESTABLE", "No configured operating evidence source has records", [f"required source not populated: {s}" for s in spec.operating_sources], test_id=spec.operating_test_id)
    rows = []
    for source, recs in present:
        rows.extend((source, r if isinstance(r, dict) else {"value": r}) for r in recs)
    examined = len(rows)
    in_scope = examined
    findings: list[str] = []
    if examined < spec.operating_min_records:
        return MASCheckResult(control_id, "operating", "NOT_TESTABLE", f"Only {examined} records available; minimum is {spec.operating_min_records}", ["insufficient operating population"], examined=examined, in_scope=in_scope, test_id=spec.operating_test_id)
    if spec.operating_required_fields:
        bad = []
        for source, row in rows:
            missing = [f for f in spec.operating_required_fields if not row.get(f) and row.get(f) not in (0, False)]
            if missing:
                bad.append(f"{source}: missing {', '.join(missing)}")
        if bad:
            findings.extend(bad[:20])
            return MASCheckResult(control_id, "operating", "FAIL", f"{len(bad)} records failed required-field checks", findings, examined=examined, in_scope=in_scope, test_id=spec.operating_test_id)

    if spec.unique_fields:
        for field in spec.unique_fields:
            vals = [str(row.get(field)).strip() for _, row in rows if row.get(field) not in (None, "")]
            dup = sorted({v for v in vals if vals.count(v) > 1})
            if dup:
                findings.append(f"duplicate {field}: {', '.join(dup[:10])}")
        if findings:
            return MASCheckResult(control_id, "operating", "FAIL", "Population uniqueness check failed", findings, examined=examined, in_scope=in_scope, test_id=spec.operating_test_id)

    if spec.ordering_pairs:
        for before, after in spec.ordering_pairs:
            for source, row in rows:
                b, a = _parse_dt(row.get(before)), _parse_dt(row.get(after))
                if b is not None and a is not None and b >= a:
                    findings.append(f"{source}: {before} must be before {after}")
        if findings:
            return MASCheckResult(control_id, "operating", "FAIL", "Temporal control-order check failed", findings[:20], examined=examined, in_scope=in_scope, test_id=spec.operating_test_id)

    return MASCheckResult(control_id, "operating", "PASS", f"{examined} operating records satisfied the executable evidence and integrity checks", [], examined=examined, in_scope=in_scope, test_id=spec.operating_test_id)


def run_control(control_id: str, evidence: dict, test_type: str = "both") -> list[MASCheckResult]:
    if control_id not in SPECS:
        raise KeyError(control_id)
    out = []
    if test_type in ("design", "both"):
        out.append(run_design(control_id, evidence))
    if test_type in ("operating", "both"):
        out.append(run_operating(control_id, evidence))
    return out


def export_catalog() -> list[dict]:
    return [{"control_id": k, **asdict(v)} for k, v in SPECS.items()]


def run_suite(evidence: dict, control_ids: list[str] | None = None, test_type: str = "both") -> dict:
    ids = control_ids or sorted(SPECS)
    results = []
    for cid in ids:
        for r in run_control(cid, evidence, test_type):
            results.append(asdict(r))
    return {"control_count": len(ids), "results": results}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run executable MAS v0.4 control tests")
    ap.add_argument("--evidence", required=True, help="JSON evidence bundle following the MAS evidence contract")
    ap.add_argument("--control", action="append", dest="controls", help="Specific control ID; repeatable")
    ap.add_argument("--type", choices=("design", "operating", "both"), default="both")
    args = ap.parse_args()
    data = json.loads(open(args.evidence, encoding="utf-8").read())
    print(json.dumps(run_suite(data, args.controls, args.type), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
