from datetime import timedelta
from pathlib import Path
import sys
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance.control_evaluator import evaluate_governed_control
from governance.observation import observe
from governance.specs import control_predicate_specs
from governance.control_contract import get_control_contract


def _obs(source, payload):
    return observe("mgf-d12-demo", source, payload, fresh_for=timedelta(days=1))


def _full_set():
    return [
        _obs("risk_methodology", {"control_id":"D1.2","methodology_id":"M-001","criteria_ref":"risk-factors","tier_scheme":"3-tier","approved_at":"2026-01-01T00:00:00+00:00"}),
        _obs("tier_rule", {"control_id":"D1.2","rule_id":"T1","rule_expression":"severity=low AND reversibility=full AND oversight=feasible","tier_outcome":"Tier 1"}),
        _obs("tier_rule", {"control_id":"D1.2","rule_id":"T2","rule_expression":"severity=moderate AND reversibility=partial AND oversight=feasible","tier_outcome":"Tier 2"}),
        _obs("risk_assessment", {"control_id":"D1.2","assessed_at":"2026-02-01T00:00:00+00:00","tier_outcome":"Tier 2"}),
        _obs("decision_record", {"control_id":"D1.2","decision_at":"2026-02-03T00:00:00+00:00"}),
        _obs("approval_record", {"control_id":"D1.2","approver_id":"approver-1","approver_role":"AI Risk Committee","requester_id":"requester-1","approved_at":"2026-02-02T00:00:00+00:00"}),
        _obs("tier_control_map", {"control_id":"D1.2","tier_outcome":"Tier 2","control_gate_id":"HITL-APPROVAL"}),
        _obs("reassessment_control", {"control_id":"D1.2","trigger_types":["material_change","incident","elapsed_time"],"detection_owner":"AI Risk","reviewed_at":"2026-02-01T00:00:00+00:00","triggers_detected":False}),
    ]


def test_d12_has_six_audited_elements():
    c = get_control_contract("D1.2", "MGF Agentic")
    assert [e["id"] for e in c["elements"]] == ["e1","e2","e3","e4","e5","e6"]
    specs = control_predicate_specs("D1.2", "MGF Agentic")
    assert set(specs) == {"e1","e2","e3","e4","e5","e6"}
    for e in c["elements"]:
        assert specs[e["id"]]["text"] == e["text"]


def test_d12_full_observation_set_passes_all_elements():
    r = evaluate_governed_control(
        control_id="D1.2", framework="MGF Agentic", resource_id="mgf-d12-demo",
        observations=_full_set(), contract_hash="d12-contract", evaluated_at="2026-02-04T00:00:00+00:00"
    )
    assert r.status == "PASS"
    assert {e.status for e in r.element_results} == {"PASS"}


def test_d12_shared_requester_approver_fails_independence():
    obs = _full_set()
    obs = [o for o in obs if o.source != "approval_record"] + [_obs("approval_record", {
        "control_id":"D1.2","approver_id":"requester-1","approver_role":"AI Risk Committee",
        "requester_id":"requester-1","approved_at":"2026-02-02T00:00:00+00:00"})]
    r = evaluate_governed_control(control_id="D1.2", framework="MGF Agentic", resource_id="mgf-d12-demo", observations=obs, contract_hash="d12-contract")
    e4 = next(e for e in r.element_results if e.element_id == "e4")
    assert e4.status == "FAIL"


def test_d12_late_assessment_fails_predecision_requirement():
    obs = [o for o in _full_set() if o.source not in {"risk_assessment","decision_record"}]
    obs += [
        _obs("risk_assessment", {"control_id":"D1.2","assessed_at":"2026-03-03T00:00:00+00:00","tier_outcome":"Tier 2"}),
        _obs("decision_record", {"control_id":"D1.2","decision_at":"2026-03-02T00:00:00+00:00"}),
    ]
    r = evaluate_governed_control(control_id="D1.2", framework="MGF Agentic", resource_id="mgf-d12-demo", observations=obs, contract_hash="d12-contract")
    e3 = next(e for e in r.element_results if e.element_id == "e3")
    assert e3.status == "FAIL"


def test_d12_empty_control_mapping_fails_load_bearing_outcome():
    obs = [o for o in _full_set() if o.source != "tier_control_map"]
    r = evaluate_governed_control(control_id="D1.2", framework="MGF Agentic", resource_id="mgf-d12-demo", observations=obs, contract_hash="d12-contract")
    e5 = next(e for e in r.element_results if e.element_id == "e5")
    assert e5.status == "NOT_TESTABLE"

def test_d12_element_registry_exposes_six_review_elements():
    from governance.element_registry import elements_for
    rows = elements_for("D1.2", "MGF Agentic")
    assert [r["element_id"] for r in rows] == ["e1", "e2", "e3", "e4", "e5", "e6"]
