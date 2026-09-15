from governance.lineage import compile_challenge, make_evidence, make_requirement_element, make_claim, make_assessment
import governance.lineage as lineage


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(lineage, "ASSESSMENTS", tmp_path/"assessments.jsonl")
    e=make_evidence(source_id="policy.pdf", source_version="sha256:doc1", locator={"page":14}, excerpt_text="Quarterly records are missing.")
    r=make_requirement_element(requirement_element_id="M3.12.e3", requirement_id="M3.12", element_text="Control operates quarterly.", version="2026-08")
    c=make_claim(claim_id="C007", element_id=r["requirement_element_id"], claim_text="The control is operating effectively in Q2.", reviewer_position="met", created_by="RR-1")
    a=make_assessment(assessment_id="GA-1", claim_id="C007", status="contradicted", evidence_citations=[{"evidence_id":e["evidence_id"],"purpose":"contradiction"}], requirement_element_id=r["requirement_element_id"], rationale="Missing records conflict with the claim.", assessed_by="CV-1")
    lineage.append_record(a, lineage.ASSESSMENTS)
    return c,e,r


def test_compiler_emits_record(tmp_path, monkeypatch):
    c,e,r=setup(tmp_path, monkeypatch)
    out=compile_challenge(draft={"target_claim_id":"C007","strength":"strong","evidence_ids":[e["evidence_id"]],"requirement_pointer":{"requirement_element_id":r["requirement_element_id"]}}, claims_by_id={"C007":c}, evidence_by_id={e["evidence_id"]:e}, requirements_by_id={r["requirement_element_id"]:r}, context_package={"context_package_id":"CP-1","versions":{"requirement_version":"2026-08","source_versions":["sha256:doc1"]}})
    assert out["compiled"] is True
    assert out["record"]["target_claim_id"] == "C007"


def test_compiler_rejects_missing_evidence(tmp_path, monkeypatch):
    c,e,r=setup(tmp_path, monkeypatch)
    out=compile_challenge(draft={"target_claim_id":"C007","strength":"strong","evidence_ids":["E-NOPE"],"requirement_pointer":{"requirement_element_id":r["requirement_element_id"]}}, claims_by_id={"C007":c}, evidence_by_id={}, requirements_by_id={r["requirement_element_id"]:r}, context_package={"versions":{"requirement_version":"2026-08"}})
    assert not out["compiled"]
    assert "EVIDENCE_NOT_FOUND" in out["errors"]


def test_compiler_rejects_version_mismatch(tmp_path, monkeypatch):
    c,e,r=setup(tmp_path, monkeypatch)
    out=compile_challenge(draft={"target_claim_id":"C007","strength":"strong","evidence_ids":[e["evidence_id"]],"requirement_pointer":{"requirement_element_id":r["requirement_element_id"]}}, claims_by_id={"C007":c}, evidence_by_id={e["evidence_id"]:e}, requirements_by_id={r["requirement_element_id"]:r}, context_package={"versions":{"requirement_version":"2026-09","source_versions":["sha256:doc1"]}})
    assert "REQUIREMENT_VERSION_MISMATCH" in out["errors"]
