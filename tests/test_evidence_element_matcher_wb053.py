from governance.evidence_element_matcher import suggest_element_matches


def test_strong_positive_match_is_suggested_as_met_not_as_a_verdict():
    elements = [{"id": "e1", "text": "Approved AI policy defines ownership and escalation expectations."}]
    evidence = "--- Source: policy.txt ---\nThe approved AI policy defines ownership and escalation expectations for AI risk."
    out = suggest_element_matches(elements, evidence, min_score=0.3)
    assert out
    assert out[0]["element_id"] == "e1"
    assert out[0]["suggested_status"] == "met"
    assert out[0]["source"] == "policy.txt"


def test_no_match_never_infers_not_evidenced():
    elements = [{"id": "e1", "text": "Quarterly committee minutes are retained."}]
    evidence = "--- Source: unrelated.txt ---\nA generic AI policy was approved."
    out = suggest_element_matches(elements, evidence)
    assert out == []
