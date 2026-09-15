import challenge as ch


def _claim(status="contradicted"):
    return {
        "claim_id": "C1",
        "claim": "The control operates monthly.",
        "element_id": "e1",
        "evidence_assessment": status,
        "evidence_reason": "test",
        "evidence_quotes": ["Monthly review completed."],
        "confidence": "high",
    }


def _raw(strength="strong", claim_id="C1"):
    return {
        "observation": "Reviewer says monthly operation is evidenced.",
        "evidence_basis": ["Monthly review completed."],
        "requirement_basis": ["Requirement"],
        "inference": "The evidence conflicts with the proposition.",
        "challenge": "Reconcile the monthly operation record.",
        "factual_pointer": {"source": "x", "locator": "line:1", "quote": "Monthly review completed.", "fact": "Monthly review completed."},
        "requirement_pointer": {"control_id": "M3.12", "element_id": "e1", "text": "Requirement"},
        "risk_to_address": "risk",
        "resolution_pointer": "record",
        "recommended_action": "answer",
        "severity": "medium",
        "confidence": "high",
        "claim_test": {"claim_id": claim_id, "claim": "The control operates monthly.", "fact_meaning": "Monthly review completed.", "rebuttal": "This conflicts with the claim.", "rebuttal_strength": strength, "risk_addressed": "risk"},
    }


def test_strong_requires_vetted_claim(monkeypatch):
    memories = []
    evidence = "--- Source: x ---\nMonthly review completed."
    monkeypatch.setattr(ch, "_requirement_pointer_context", lambda *a: ("req", [{"id":"e1","text":"Requirement","scope":"model","applies_when":None,"locator":"controls.M3.12.elements[0]"}], {}, "contract"))
    out = ch._validate_structured({"challenges": [_raw()]}, memories, evidence, "M3.12", reviewer_read={}, vetted_claims=[])
    assert out["challenges"][0]["challenge_strength"] == "rejected"


def test_strong_allowed_only_for_contradicted(monkeypatch):
    memories = []
    evidence = "--- Source: x ---\nMonthly review completed."
    monkeypatch.setattr(ch, "_requirement_pointer_context", lambda *a: ("req", [{"id":"e1","text":"Requirement","scope":"model","applies_when":None,"locator":"controls.M3.12.elements[0]"}], {}, "contract"))
    supported = ch._validate_structured({"challenges": [_raw()]}, memories, evidence, "M3.12", reviewer_read={}, vetted_claims=[_claim("supported")])
    contradicted = ch._validate_structured({"challenges": [_raw()]}, memories, evidence, "M3.12", reviewer_read={}, vetted_claims=[_claim("contradicted")])
    assert supported["challenges"][0]["challenge_strength"] == "weak"
    assert contradicted["challenges"][0]["challenge_strength"] == "strong"


def test_missing_claim_id_is_rejected(monkeypatch):
    memories = []
    evidence = "--- Source: x ---\nMonthly review completed."
    raw = _raw(claim_id="")
    raw["claim_test"].pop("claim_id")
    monkeypatch.setattr(ch, "_requirement_pointer_context", lambda *a: ("req", [{"id":"e1","text":"Requirement","scope":"model","applies_when":None,"locator":"controls.M3.12.elements[0]"}], {}, "contract"))
    out = ch._validate_structured({"challenges": [raw]}, memories, evidence, "M3.12", reviewer_read={}, vetted_claims=[_claim("contradicted")])
    assert out["challenges"][0]["challenge_strength"] == "rejected"
