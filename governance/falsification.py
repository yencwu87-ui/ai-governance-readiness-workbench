"""v0.7 Falsification Engine.

LLMs may propose falsification probes; this module decides whether a probe is admissible.
A probe is always lineage-bound to a vetted ClaimRecord and its governed RequirementElement.
It does not change a governance decision. It produces executable tests/evidence requests.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable

from governance.claim_register import resolve_claim

PROBE_TYPES = {"counterfactual", "missing_condition", "alternative_interpretation", "evidence_request"}
STATUSES = {"proposed", "ready", "blocked", "executed", "resolved"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def probe_id(claim_id: str, probe_type: str, test: str) -> str:
    return "FP-" + _digest({"claim_id": claim_id, "probe_type": probe_type, "test": " ".join(str(test).split())})


def _normalise_type(value: object) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return raw


def _normalise_claims(claims: Iterable[dict]) -> list[dict]:
    return [dict(x) for x in (claims or []) if isinstance(x, dict)]


def admissibility(claim: dict | None, probe_type: str, *, requirement_element_id: str, evidence_ids: list[str],
                  context_package_id: str | None = None) -> dict:
    """Deterministic eligibility gate for a falsification probe."""
    ptype = _normalise_type(probe_type)
    if claim is None:
        return {"status": "blocked", "reason_code": "CLAIM_NOT_REGISTERED"}
    if not str(claim.get("claim_id") or "").strip():
        return {"status": "blocked", "reason_code": "CLAIM_ID_MISSING"}
    if ptype not in PROBE_TYPES:
        return {"status": "blocked", "reason_code": "INVALID_PROBE_TYPE"}
    if str(requirement_element_id or "") != str(claim.get("element_id") or ""):
        return {"status": "blocked", "reason_code": "REQUIREMENT_ELEMENT_MISMATCH"}
    if not context_package_id:
        return {"status": "blocked", "reason_code": "CONTEXT_PACKAGE_MISSING"}
    if ptype == "counterfactual" and str(claim.get("evidence_assessment") or "unclear") == "unsupported":
        return {"status": "blocked", "reason_code": "UNSUPPORTED_CLAIM_NEEDS_EVIDENCE_REQUEST"}
    if ptype in {"counterfactual", "missing_condition", "alternative_interpretation"} and not evidence_ids:
        return {"status": "blocked", "reason_code": "EVIDENCE_CONTEXT_MISSING"}
    return {"status": "ready", "reason_code": "ADMISSIBLE"}


def compile_probe(draft: dict, claims: Iterable[dict], *, evidence_ledger: dict[str, dict],
                  requirement_elements: dict[str, dict], context_package_id: str,
                  context_package: dict | None = None) -> dict:
    """Compile an LLM Challenge/Falsification draft into an engine-owned FalsificationProbe."""
    if not isinstance(draft, dict):
        raise ValueError("falsification draft must be an object")
    claim_id = str(draft.get("target_claim_id") or "").strip()
    claim = resolve_claim(claims, claim_id=claim_id)
    if claim is None:
        raise ValueError("CLAIM_NOT_REGISTERED")
    element_id = str(draft.get("requirement_element_id") or "").strip()
    if element_id not in requirement_elements:
        raise ValueError("REQUIREMENT_ELEMENT_NOT_REGISTERED")
    if element_id != str(claim.get("element_id") or ""):
        raise ValueError("REQUIREMENT_ELEMENT_MISMATCH")
    evidence_ids = [str(x).strip() for x in (draft.get("evidence_ids") or []) if str(x).strip()]
    missing_evidence = [eid for eid in evidence_ids if eid not in evidence_ledger]
    if missing_evidence:
        raise ValueError("EVIDENCE_NOT_REGISTERED:" + ",".join(missing_evidence))
    ptype = _normalise_type(draft.get("probe_type"))
    test = " ".join(str(draft.get("test") or "").split())
    expected = " ".join(str(draft.get("falsifies_if") or "").split())
    if not test or not expected:
        raise ValueError("PROBE_TEST_OR_FALSIFICATION_CONDITION_MISSING")
    gate = admissibility(claim, ptype, requirement_element_id=element_id, evidence_ids=evidence_ids,
                         context_package_id=context_package_id)
    if gate["status"] != "ready":
        raise ValueError(gate["reason_code"])
    package = context_package or {}
    if package.get("context_package_id") and package["context_package_id"] != context_package_id:
        raise ValueError("CONTEXT_PACKAGE_MISMATCH")
    record = {
        "probe_id": probe_id(claim_id, ptype, test),
        "claim_id": claim_id,
        "claim_fingerprint": claim.get("claim_fingerprint"),
        "requirement_element_id": element_id,
        "evidence_ids": evidence_ids,
        "probe_type": ptype,
        "test": test,
        "falsifies_if": expected,
        "success_criteria": [str(x).strip() for x in (draft.get("success_criteria") or []) if str(x).strip()],
        "evidence_to_collect": [str(x).strip() for x in (draft.get("evidence_to_collect") or []) if str(x).strip()],
        "reason_codes": [str(x).strip() for x in (draft.get("reason_codes") or []) if str(x).strip()],
        "context_package_id": context_package_id,
        "status": "ready",
        "compiled_at": _now(),
        "compiled_by": "falsification_compiler:v0.7",
    }
    if not record["success_criteria"]:
        record["success_criteria"] = ["Observed result satisfies the stated falsification condition or leaves it unresolved."]
    return record


def build_context_package(*, control_id: str, claim_ids: list[str], evidence_ids: list[str],
                          requirement_element_ids: list[str], model: str, prompt_version: str,
                          source_versions: dict[str, str] | None = None) -> dict:
    payload = {"control_id": control_id, "claim_ids": sorted(claim_ids), "evidence_ids": sorted(evidence_ids),
               "requirement_element_ids": sorted(requirement_element_ids), "source_versions": source_versions or {},
               "model": model, "prompt_version": prompt_version}
    return {"context_package_id": "CP-" + _digest(payload), "schema": "v0.7.context-package.1", **payload,
            "created_at": _now()}


def coverage(probes: Iterable[dict], claims: Iterable[dict]) -> dict:
    rows = _normalise_claims(claims)
    ids = [str(c.get("claim_id")) for c in rows if c.get("claim_id")]
    by_claim = {cid: [] for cid in ids}
    for p in probes or []:
        if isinstance(p, dict) and p.get("claim_id") in by_claim and p.get("status") in {"ready", "executed", "resolved"}:
            by_claim[p["claim_id"]].append(p.get("probe_type"))
    covered = [cid for cid, types in by_claim.items() if types]
    return {"claim_count": len(ids), "covered_claims": len(covered),
            "coverage_ratio": (len(covered) / len(ids)) if ids else 0.0,
            "uncovered_claim_ids": [cid for cid, types in by_claim.items() if not types],
            "probe_types_by_claim": by_claim}


def build_evidence_ledger(claims: Iterable[dict], evidence_text: str) -> dict[str, dict]:
    """Create a deterministic, content-addressed ledger for evidence excerpts used by v0.7.

    This is the MVP persistence boundary: source version is the hash of the supplied evidence
    bundle, while excerpt identity is derived from source/locator/quote. A later DB adapter can
    persist these exact records without changing probe semantics.
    """
    bundle_hash = "sha256:" + hashlib.sha256((evidence_text or "").encode("utf-8")).hexdigest()
    ledger = {}
    for claim in claims or []:
        for idx, quote in enumerate(claim.get("evidence_quotes") or [], 1):
            q = " ".join(str(quote).split())
            if not q:
                continue
            eid = "E-" + hashlib.sha256(json.dumps({"source":"supplied_evidence","locator":str(idx),"quote":q}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
            ledger[eid] = {"evidence_id": eid, "source_id": "supplied_evidence", "source_version": bundle_hash,
                           "locator": {"kind":"sequence", "value": idx}, "excerpt_text": q,
                           "excerpt_hash": "sha256:" + hashlib.sha256(q.encode("utf-8")).hexdigest(),
                           "classification": "organizational_evidence"}
    return ledger


def generate_probe_drafts(claims: Iterable[dict]) -> list[dict]:
    """Generate bounded falsification hypotheses; the compiler remains authoritative."""
    drafts = []
    for claim in claims or []:
        if not isinstance(claim, dict) or not claim.get("claim_id") or not claim.get("element_id"):
            continue
        cid = claim["claim_id"]
        evidence_ids = list(claim.get("evidence_ids") or [])
        status = str(claim.get("evidence_assessment") or "unclear")
        if status in {"supported", "contradicted", "unclear"} and evidence_ids:
            drafts.append({"target_claim_id":cid,"requirement_element_id":claim["element_id"],"evidence_ids":evidence_ids,
                           "probe_type":"counterfactual","test":"Test the minimum condition under which the reviewer proposition would fail.",
                           "falsifies_if":"The observed test result is inconsistent with the reviewer proposition."})
            drafts.append({"target_claim_id":cid,"requirement_element_id":claim["element_id"],"evidence_ids":evidence_ids,
                           "probe_type":"missing_condition","test":"Identify the necessary condition, exception, or operating circumstance not established by the current evidence.",
                           "falsifies_if":"A necessary condition for the proposition is absent or unverified."})
        if status in {"supported", "unclear"} and evidence_ids:
            drafts.append({"target_claim_id":cid,"requirement_element_id":claim["element_id"],"evidence_ids":evidence_ids,
                           "probe_type":"alternative_interpretation","test":"Test whether the same evidence has a materially different interpretation under the governed requirement.",
                           "falsifies_if":"An alternative governed interpretation better explains the evidence and defeats the reviewer proposition."})
        if status in {"unsupported", "unclear"}:
            drafts.append({"target_claim_id":cid,"requirement_element_id":claim["element_id"],"evidence_ids":evidence_ids,
                           "probe_type":"evidence_request","test":"Obtain the missing artefact needed to establish or falsify the reviewer proposition.",
                           "falsifies_if":"The requested artefact fails to establish the proposition or reveals contrary operation."})
    return drafts


def compile_plan(*, control_id: str, claims: list[dict], evidence_text: str, requirement_elements: dict[str, dict],
                 model: str, prompt_version: str) -> dict:
    ledger = build_evidence_ledger(claims, evidence_text)
    # Claim evidence IDs are deterministic and must point into this exact ledger.
    for claim in claims:
        claim["evidence_ids"] = [eid for eid in claim.get("evidence_ids", []) if eid in ledger]
    package = build_context_package(control_id=control_id, claim_ids=[c.get("claim_id") for c in claims if c.get("claim_id")],
                                    evidence_ids=list(ledger), requirement_element_ids=[c.get("element_id") for c in claims if c.get("element_id")],
                                    model=model, prompt_version=prompt_version,
                                    source_versions={eid: row["source_version"] for eid,row in ledger.items()})
    probes = []
    blocked = []
    for draft in generate_probe_drafts(claims):
        try:
            probes.append(compile_probe(draft, claims, evidence_ledger=ledger, requirement_elements=requirement_elements,
                                        context_package_id=package["context_package_id"], context_package=package))
        except ValueError as exc:
            blocked.append({"target_claim_id":draft.get("target_claim_id"),"probe_type":draft.get("probe_type"),"reason":str(exc)})
    return {"schema":"v0.7.falsification-engine.1", "context_package":package, "evidence_ledger":ledger,
            "probes":probes, "blocked_probes":blocked, "coverage":coverage(probes, claims)}
