"""GE-116 real predicate specifications and service/UI seams."""
from datetime import timedelta
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.control_evaluator import evaluate_governed_control
from governance.observation import observe
from governance.specs import control_predicate_specs


def _obs(subject, source, payload):
    return observe(subject, source, payload, fresh_for=timedelta(days=1))


def test_m36_has_real_predicate_spec_for_all_in_scope_elements():
    specs = control_predicate_specs("M3.6")
    assert set(specs) == {f"e{i}" for i in range(1, 15)}
    assert specs["e14"]["observability"] == "out_of_band"
    assert all(specs[e].get("predicates") for e in specs if e != "e14")


def test_m36_e1_passes_when_criteria_precede_test():
    obs = [
        _obs("m36", "evaluation_criteria", {"control_id": "M3.6", "measure_id": "auc", "threshold": 0.65, "defined_at": "2026-01-01T00:00:00+00:00"}),
        _obs("m36", "test_run", {"control_id": "M3.6", "use_case_id": "u1", "started_at": "2026-02-01T00:00:00+00:00", "representativeness": "representative", "plausible_conditions": True, "results_ref": "r1"}),
    ]
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=obs, contract_hash="c1", evaluated_at="2026-02-02T00:00:00+00:00")
    e1 = next(x for x in r.element_results if x.element_id == "e1")
    assert e1.status == "PASS"


def test_m36_e4_becomes_not_applicable_when_precondition_false():
    obs = [_obs("m36", "risk_assessment", {"control_id": "M3.6", "robustness_relevant": False})]
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=obs, contract_hash="c1")
    e4 = next(x for x in r.element_results if x.element_id == "e4")
    assert e4.status == "NOT_APPLICABLE"


def test_m36_e4_is_not_testable_when_applicability_source_missing():
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=[], contract_hash="c1")
    e4 = next(x for x in r.element_results if x.element_id == "e4")
    assert e4.status == "NOT_TESTABLE"


def test_m36_e14_is_not_scored_as_an_observation_verdict():
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=[], contract_hash="c1")
    assert all(e.element_id != "e14" for e in r.element_results)


def test_app_engine_surface_contains_no_predicate_execution_logic():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    body = source[source.find("# ---------------------------------------------------------------- Governance Engine / GE-116"):]
    assert "field_present" not in body
    assert "predicate_engine" not in body
    assert "evaluate_governed_control" not in body


def test_m36_e1_fails_when_threshold_was_defined_after_testing():
    obs = [
        _obs("m36", "evaluation_criteria", {"control_id": "M3.6", "measure_id": "auc", "threshold": 0.65, "defined_at": "2026-03-01T00:00:00+00:00"}),
        _obs("m36", "test_run", {"control_id": "M3.6", "use_case_id": "u1", "started_at": "2026-02-01T00:00:00+00:00", "representativeness": "representative", "plausible_conditions": True, "results_ref": "r1"}),
    ]
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=obs, contract_hash="c1", evaluated_at="2026-03-02T00:00:00+00:00")
    e1 = next(x for x in r.element_results if x.element_id == "e1")
    assert e1.status == "FAIL"


def test_truthy_predicate_does_not_pass_false_boolean_fields():
    obs = [_obs("m36", "test_coverage", {"performance": True, "error_conditions": True, "failure_conditions": True, "edge_cases": True, "robustness_security_adversarial": False})]
    risk = [_obs("m36", "risk_assessment", {"control_id": "M3.6", "robustness_relevant": True})]
    r = evaluate_governed_control(control_id="M3.6", resource_id="m36", observations=obs + risk, contract_hash="c1")
    e4 = next(x for x in r.element_results if x.element_id == "e4")
    assert e4.status == "FAIL"


def test_predicate_spec_text_matches_governed_requirement_text():
    import yaml
    contract = yaml.safe_load((ROOT / "requirements" / "mas.yaml").read_text(encoding="utf-8"))
    contract_texts = {e["id"]: e["text"] for e in contract["controls"]["M3.6"]["elements"]}
    specs = control_predicate_specs("M3.6")
    for eid, spec in specs.items():
        assert spec.get("text") == contract_texts[eid]
