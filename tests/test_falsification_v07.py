import pytest
from governance.falsification import compile_probe, build_context_package, coverage


def claim(status="supported"):
    return {"claim_id":"C1","claim":"The control operates monthly.","element_id":"e1",
            "evidence_assessment":status,"claim_fingerprint":"fp1"}


def ledger():
    return {"E1":{"evidence_id":"E1","source_version":"sha256:abc","excerpt_hash":"sha256:def"}}


def elements():
    return {"e1":{"requirement_element_id":"e1","version":"2026-08"}}


def test_counterfactual_compiles_only_with_lineage():
    cp=build_context_package(control_id="M3.12",claim_ids=["C1"],evidence_ids=["E1"],requirement_element_ids=["e1"],model="m",prompt_version="p1")
    out=compile_probe({"target_claim_id":"C1","requirement_element_id":"e1","evidence_ids":["E1"],
        "probe_type":"counterfactual","test":"Verify one quarter where the control did not operate.",
        "falsifies_if":"The claimed monthly operation cannot be demonstrated."}, [claim()], evidence_ledger=ledger(), requirement_elements=elements(), context_package_id=cp["context_package_id"], context_package=cp)
    assert out["status"] == "ready"
    assert out["probe_id"].startswith("FP-")


def test_unknown_evidence_is_rejected():
    cp=build_context_package(control_id="M3.12",claim_ids=["C1"],evidence_ids=["E9"],requirement_element_ids=["e1"],model="m",prompt_version="p1")
    with pytest.raises(ValueError, match="EVIDENCE_NOT_REGISTERED"):
        compile_probe({"target_claim_id":"C1","requirement_element_id":"e1","evidence_ids":["E9"],"probe_type":"missing_condition","test":"Find the missing condition.","falsifies_if":"Condition absent."}, [claim()], evidence_ledger=ledger(), requirement_elements=elements(), context_package_id=cp["context_package_id"], context_package=cp)


def test_unsupported_claim_routes_to_evidence_request():
    cp=build_context_package(control_id="M3.12",claim_ids=["C1"],evidence_ids=[],requirement_element_ids=["e1"],model="m",prompt_version="p1")
    with pytest.raises(ValueError, match="UNSUPPORTED_CLAIM_NEEDS_EVIDENCE_REQUEST"):
        compile_probe({"target_claim_id":"C1","requirement_element_id":"e1","evidence_ids":[],"probe_type":"counterfactual","test":"Test it.","falsifies_if":"Claim fails."}, [claim("unsupported")], evidence_ledger={}, requirement_elements=elements(), context_package_id=cp["context_package_id"], context_package=cp)


def test_coverage_is_claim_level():
    probes=[{"claim_id":"C1","probe_type":"missing_condition","status":"ready"}]
    out=coverage(probes,[claim(),{"claim_id":"C2"}])
    assert out["covered_claims"] == 1
    assert out["uncovered_claim_ids"] == ["C2"]
