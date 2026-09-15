"""v0.6 immutable governance lineage and deterministic challenge compiler.

JSONL is the MVP persistence layer: records are append-only snapshots and identities are
content-addressed. The public compiler boundary is intentionally independent of the LLM.
"""
from __future__ import annotations

import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "evidence_ledger.jsonl"
CLAIMS = ROOT / "claim_register.jsonl"
ASSESSMENTS = ROOT / "grounding_assessments.jsonl"
CHALLENGES = ROOT / "challenge_records.jsonl"


def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def digest(v): return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
def content_hash(v): return "sha256:" + digest(v)

def evidence_key(source_version, locator, excerpt_hash):
    return "E-" + digest({"source_version": source_version, "locator": locator, "excerpt_hash": excerpt_hash})[:12]

def make_evidence(*, source_id, source_version, locator, excerpt_text, classification="organizational_evidence", captured_at=None):
    excerpt_hash = content_hash(" ".join(str(excerpt_text).split()))
    return {"evidence_id": evidence_key(source_version, locator, excerpt_hash), "source_id": source_id,
            "source_version": source_version, "locator": locator, "excerpt_text": excerpt_text,
            "excerpt_hash": excerpt_hash, "captured_at": captured_at or now(), "classification": classification}

def make_requirement_element(*, requirement_element_id, requirement_id, element_text, test_type="", jurisdiction="", version=""):
    return {"requirement_element_id": requirement_element_id, "requirement_id": requirement_id,
            "element_text": element_text, "test_type": test_type, "jurisdiction": jurisdiction, "version": version}

def make_claim(*, claim_id, element_id, claim_text, reviewer_position, created_by, created_at=None):
    return {"claim_id": claim_id, "element_id": element_id, "claim_text": claim_text,
            "reviewer_position": reviewer_position, "created_at": created_at or now(), "created_by": created_by}

def make_assessment(*, assessment_id, claim_id, status, evidence_citations, requirement_element_id, rationale, assessed_by, created_at=None, reason_codes=None):
    if status not in {"supported", "contradicted", "unsupported", "unclear"}: raise ValueError("invalid grounding status")
    if status == "contradicted" and not evidence_citations: raise ValueError("contradicted assessment requires evidence citations")
    return {"assessment_id": assessment_id, "claim_id": claim_id, "status": status,
            "evidence_citations": evidence_citations, "requirement_element_id": requirement_element_id,
            "rationale": rationale, "assessed_by": assessed_by, "created_at": created_at or now(),
            "reason_codes": list(reason_codes or [])}

def append_record(record, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f: f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record

def load_records(path):
    if not path.exists(): return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

def latest_assessment(claim_id, path=None):
    path = path or ASSESSMENTS
    rows = [r for r in load_records(path) if r.get("claim_id") == claim_id]
    return rows[-1] if rows else None

def compile_challenge(*, draft, claims_by_id, evidence_by_id, requirements_by_id, context_package):
    """Compile an LLM draft into a dossier-eligible ChallengeRecord or reject it."""
    errors=[]
    cid=str(draft.get("target_claim_id") or draft.get("claim_id") or "")
    claim=claims_by_id.get(cid)
    if not claim: errors.append("TARGET_CLAIM_NOT_FOUND")
    reqid=str((draft.get("requirement_pointer") or {}).get("requirement_element_id") or (draft.get("requirement_pointer") or {}).get("element_id") or "")
    req=requirements_by_id.get(reqid)
    if not req: errors.append("REQUIREMENT_ELEMENT_NOT_FOUND")
    cited=[]
    for eid in draft.get("evidence_ids") or []:
        e=evidence_by_id.get(str(eid))
        if not e: errors.append("EVIDENCE_NOT_FOUND"); continue
        cited.append(e)
    strength=str(draft.get("strength") or draft.get("challenge_strength") or "weak").lower()
    if strength not in {"strong","weak","evidence_request","rejected"}: errors.append("INVALID_STRENGTH")
    assessment=latest_assessment(cid) if claim else None
    if claim and assessment:
        allowed={"contradicted":{"strong","weak"},"supported":{"weak"},"unsupported":{"evidence_request","weak"},"unclear":{"evidence_request","weak"}}.get(assessment.get("status"),set())
        if strength not in allowed: errors.append("STRENGTH_NOT_ADMISSIBLE")
    elif claim: errors.append("NO_GROUNDING_ASSESSMENT")
    run_versions=context_package.get("versions",{})
    if req and run_versions.get("requirement_version") and req.get("version") and req.get("version") != run_versions["requirement_version"]: errors.append("REQUIREMENT_VERSION_MISMATCH")
    if cited and run_versions.get("source_versions"):
        allowed_versions=set(run_versions["source_versions"])
        if any(e.get("source_version") not in allowed_versions for e in cited): errors.append("EVIDENCE_VERSION_MISMATCH")
    if errors: return {"compiled":False,"errors":sorted(set(errors))}
    record={"challenge_id":"CH-"+digest({"claim":cid,"draft":draft,"context":context_package})[:12],
            "target_claim_id":cid,"strength":strength,"argument_graph_id":draft.get("argument_graph_id"),
            "evidence_ids":[e["evidence_id"] for e in cited],"requirement_element_id":reqid,
            "context_package_id":context_package.get("context_package_id"),"compiled_at":now(),
            "compiled_by":"challenge_compiler:v0.6","status":"open","draft":dict(draft)}
    return {"compiled":True,"record":record}
