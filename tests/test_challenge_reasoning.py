from challenge import _validate_structured
from requirements_overlay import load_overlay

_REQ_PTR = {"control_id": "M3.12", "element_id": "e1", "text": next(
    e["text"] for e in (load_overlay()["controls"]["M3.12"]["elements"] or []) if isinstance(e, dict) and e.get("id") == "e1"
), "locator": "controls.M3.12.elements[1]"}


def test_structured_challenge_requires_grounded_reasoning():
    memories = [{"memory_id": "GOV-MEM-1"}]
    out = _validate_structured({
        "overall_reasoning": "Approval evidence does not demonstrate verification.",
        "challenges": [{
            "observation": "Reviewer called the control full.",
            "evidence_basis": ["WB-025 has approval but no verification field."],
            "requirement_basis": ["Post-implementation verification is required."],
            "knowledge_basis": [{"memory_id": "GOV-MEM-1", "role": "precedent"}],
            "inference": "The evidence demonstrates approval, not verification.",
            "challenge": "What evidence demonstrates post-implementation verification?",
            "factual_pointer": {"source": "WB-025", "locator": "matched_quote", "quote": "WB-025 has approval but no verification field."},
            "requirement_pointer": _REQ_PTR,
            "risk_to_address": "Successful implementation may be unverified.",
            "resolution_pointer": "Provide the post-implementation verification record for WB-025.",
            "recommended_action": "request_evidence",
            "severity": "high",
            "confidence": "high",
        }],
        "sharpest": "What evidence demonstrates post-implementation verification?",
        "unaddressed": [],
    }, memories, "--- Source: WB-025 ---\nWB-025 has approval but no verification field.", "M3.12")
    assert out["challenges"][0]["recommended_action"] == "request_evidence"


def test_structured_challenge_rejects_unknown_memory_reference():
    try:
        _validate_structured({
            "challenges": [{
                "observation": "claim", "evidence_basis": ["e"], "requirement_basis": ["r"],
                "knowledge_basis": [{"memory_id": "UNKNOWN"}], "inference": "i",
                "challenge": "c", "factual_pointer": {"quote": "e"},
                "requirement_pointer": _REQ_PTR,
                "risk_to_address": "risk", "resolution_pointer": "resolution",
                "recommended_action": "answer", "severity": "low", "confidence": "low",
            }]
        }, [{"memory_id": "KNOWN"}], "e", "M3.12")
    except ValueError as e:
        assert "unknown knowledge memory" in str(e)
    else:
        raise AssertionError("unknown knowledge memory must be rejected")


def test_factual_pointer_must_match_supplied_evidence():
    payload = {
        "challenges": [{
            "observation": "claim", "evidence_basis": ["e"], "requirement_basis": ["r"],
            "knowledge_basis": [], "inference": "i", "challenge": "c",
            "factual_pointer": {"quote": "not actually supplied"},
            "requirement_pointer": _REQ_PTR,
            "risk_to_address": "risk", "resolution_pointer": "resolution",
            "recommended_action": "request_evidence", "severity": "medium", "confidence": "high",
        }]
    }
    try:
        _validate_structured(payload, [], "--- Source: WB-025 ---\nactual evidence", "M3.12")
    except ValueError as e:
        assert "not verifiable" in str(e)
    else:
        raise AssertionError("an unverifiable factual pointer must be rejected")


def test_structured_challenge_backfills_redundant_basis_from_verified_pointers():
    out = _validate_structured({
        "challenges": [{
            "observation": "claim",
            "evidence_basis": [],
            "requirement_basis": [],
            "knowledge_basis": [],
            "inference": "i",
            "challenge": "c",
            "factual_pointer": {"quote": "actual evidence"},
            "requirement_pointer": _REQ_PTR,
            "risk_to_address": "risk",
            "resolution_pointer": "resolution",
            "recommended_action": "request_evidence",
            "severity": "medium",
            "confidence": "high",
        }]
    }, [], "--- Source: WB-025 ---\nactual evidence", "M3.12")
    assert out["challenges"][0]["evidence_basis"] == ["actual evidence"]
    assert out["challenges"][0]["requirement_basis"] == [_REQ_PTR["text"]]
