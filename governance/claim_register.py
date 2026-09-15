"""Evidence-lineage primitives for grounded reviewer claims and challenges.

The register is deliberately small and deterministic. LLMs may propose claims and rebuttals,
but admissibility is decided here: a challenge must identify a vetted claim, and a substantive
(strong) rebuttal requires a claim whose supplied evidence was actually classified contradicted.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

GROUNDED_STATUSES = {"supported", "contradicted", "unsupported", "unclear"}
STRONG_ALLOWED_STATUSES = {"contradicted"}


def claim_fingerprint(claim: str, element_id: str = "") -> str:
    payload = {"claim": " ".join(str(claim).split()), "element_id": str(element_id or "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def normalise_claims(claims: Iterable[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for idx, claim in enumerate(claims or [], 1):
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("claim_id") or f"C{idx}").strip()
        if not cid:
            continue
        row = dict(claim)
        row["claim_id"] = cid
        row["claim_fingerprint"] = claim_fingerprint(row.get("claim", ""), row.get("element_id", ""))
        row["challenge_eligible"] = row.get("evidence_assessment") in GROUNDED_STATUSES
        out[cid] = row
    return out


def resolve_claim(claims: Iterable[dict], claim_id: str | None = None, claim_text: str | None = None) -> dict | None:
    register = normalise_claims(claims)
    if claim_id and claim_id in register:
        return register[claim_id]
    target = " ".join(str(claim_text or "").split()).lower()
    if not target:
        return None
    for row in register.values():
        if " ".join(str(row.get("claim", "")).split()).lower() == target:
            return row
    return None


def gate_challenge(claim: dict | None, requested_strength: str) -> dict:
    """Return the only admissible challenge strength for a vetted claim."""
    requested = str(requested_strength or "weak").lower()
    if requested not in {"strong", "weak", "rejected"}:
        requested = "weak"
    if claim is None:
        return {"strength": "rejected", "substantive": False, "reason": "challenge targets no vetted claim"}
    status = str(claim.get("evidence_assessment") or "unclear").lower()
    if requested == "strong" and status not in STRONG_ALLOWED_STATUSES:
        return {"strength": "weak", "substantive": False,
                "reason": f"strong rebuttal requires contradicted claim evidence; claim is {status}"}
    return {"strength": requested, "substantive": requested == "strong"}


def evidence_id(source: str, locator: str, quote: str) -> str:
    payload = {"source": str(source or ""), "locator": str(locator or ""), "quote": " ".join(str(quote or "").split())}
    return "E-" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def enrich_claim(claim: dict) -> dict:
    row = dict(claim)
    row["claim_fingerprint"] = claim_fingerprint(row.get("claim", ""), row.get("element_id", ""))
    row["grounding_status"] = row.get("evidence_assessment", "unclear")
    row["evidence_ids"] = list(row.get("evidence_ids") or [])
    return row
