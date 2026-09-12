from challenge import _claim_test, _validate_claim_rebuttal


def test_missing_claim_test_is_conservative_weak():
    ct = _claim_test({
        "observation": "Reviewer says Full.",
        "factual_pointer": {"what_it_supports": "Approval exists."},
        "inference": "Approval is relevant but does not prove verification.",
        "risk_to_address": "Unverified operation.",
    })
    assert ct["rebuttal_strength"] == "weak"
    assert ct["claim"] == "Reviewer says Full."


def test_explicit_non_rebuttal_cannot_be_strong():
    ct = _claim_test({
        "claim_test": {
            "claim": "No system boundary is evidenced.",
            "fact_meaning": "A framework is board-approved.",
            "rebuttal": "This does not establish the system boundary.",
            "rebuttal_strength": "strong",
            "risk_addressed": "Unbounded use case.",
        }
    })
    gate = _validate_claim_rebuttal(
        claim_test=ct,
        factual_pointer={"quote": "Framework approved.", "fact": "Framework approved."},
        reviewer_read={"reason": "No boundary evidence."},
    )
    assert gate["strength"] == "weak"
    assert not gate["substantive"]


def test_relevant_but_non_rebutting_fact_is_marked_weak():
    ct = _claim_test({
        "claim_test": {
            "claim": "No system-specific boundary is evidenced.",
            "fact_meaning": "The enterprise AI framework is approved.",
            "rebuttal": "The approval does not demonstrate the system-specific boundary.",
            "rebuttal_strength": "strong",
            "risk_addressed": "Unbounded system use.",
        }
    })
    assert ct["rebuttal_strength"] == "strong"
    gate = _validate_claim_rebuttal(
        claim_test=ct,
        factual_pointer={"quote": "Framework approved.", "fact": "Framework approved."},
        reviewer_read={"reason": "No system boundary is evidenced."},
    )
    assert gate["strength"] == "weak"
