from pathlib import Path
import json

from governance.assessment_identity import build_assessment_identity
from governance.register_checks import validate_ticket_register
from governance.release_gate import evaluate_release_gate

ROOT = Path(__file__).resolve().parents[1]


def test_assessment_identity_changes_when_requirement_changes(tmp_path):
    req = tmp_path / "requirements.yaml"
    req.write_text("M3.6: one\n")
    a = build_assessment_identity(
        engine_version="v0.4.0", model="test/model@1", git_sha="abc", artefacts=[req]
    )
    req.write_text("M3.6: two\n")
    b = build_assessment_identity(
        engine_version="v0.4.0", model="test/model@1", git_sha="abc", artefacts=[req]
    )
    assert a["assessment_id"] != b["assessment_id"]


def test_assessment_identity_is_stable_for_same_inputs(tmp_path):
    req = tmp_path / "requirements.yaml"
    req.write_text("M3.6: one\n")
    kwargs = dict(engine_version="v0.4.0", model="test/model@1", git_sha="abc", artefacts=[req])
    assert build_assessment_identity(**kwargs)["assessment_id"] == build_assessment_identity(**kwargs)["assessment_id"]


def test_ticket_register_detects_duplicate(tmp_path):
    p = tmp_path / "tickets.csv"
    p.write_text(
        "ticket_id,model_id,version,risk_tier,approver,emergency,opened_at,approved_at,description\n"
        "WB-001,m,v1,medium,R,FALSE,2026-09-01,2026-09-01,x\n"
        "WB-001,m,v1,medium,R,FALSE,2026-09-01,2026-09-01,y\n"
    )
    result = validate_ticket_register(p)
    assert any("duplicate ticket_id WB-001" in e for e in result["errors"])


def test_release_gate_passes_clean_result():
    summary = {
        "status": "evaluated", "accuracy": .90, "adjacent_accuracy": .98,
        "over_credit_rate": 0, "refusal_rate": 0, "quarantine_rate": 0,
        "baseline_margin": .20,
        "accuracy_by_kind": {"real": {"accuracy": .95}},
    }
    assert evaluate_release_gate(summary)["status"] == "PASS"


def test_release_gate_fails_current_llama_result():
    summary = json.loads((ROOT / "governance" / "eval_results.json").read_text())[-1]
    result = evaluate_release_gate(summary)
    assert result["status"] == "FAIL"
    assert "accuracy" in result["failed"]
    assert "over_credit_rate" in result["failed"]


def test_all_critical_controls_have_explicit_assurance_mode():
    import yaml
    req = yaml.safe_load((ROOT / "requirements" / "mas.yaml").read_text())
    critical = {cid: e for cid, e in req["test_controls"].items() if e.get("severity") == "critical"}
    assert critical
    assert all(e.get("assurance_mode") in {"lane_b", "human_only", "hybrid", "lane_a"}
               for e in critical.values())


def test_ticket_register_references_are_reconciled():
    result = validate_ticket_register(ROOT / "governance" / "tickets.csv", root=ROOT)
    assert not [e for e in result["errors"] if "absent from register" in e], result["errors"]
    assert len(result["ticket_ids"]) >= 30


def test_link_checker_has_no_reference_errors():
    from governance.link_check import run
    result = run()
    assert result["errors"] == [], result["errors"]


def test_eight_critical_controls_have_real_semantic_definitions():
    import yaml
    req = yaml.safe_load((ROOT / "requirements" / "mas.yaml").read_text())
    defs = req["controls"]
    for cid in ["M1.1", "M3.6", "M3.7", "M3.9", "M3.11", "M3.12", "F1", "F3"]:
        entry = defs[cid]
        assert entry.get("requirement") and not str(entry["requirement"]).startswith("TODO")
        assert len(entry.get("elements") or []) >= 3
        assert set((entry.get("boundary") or {})) >= {"none", "partial", "full"}


def test_retriever_has_bm25_fallback():
    from retriever import BM25Okapi
    idx = BM25Okapi([["alpha", "beta"], ["gamma"]])
    scores = idx.get_scores(["alpha"])
    assert scores[0] > scores[1]
