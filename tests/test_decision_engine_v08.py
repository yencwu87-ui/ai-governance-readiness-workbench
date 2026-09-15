import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.decision_engine import evaluate, enforce


def test_full_is_blocked_by_contradicted_claim():
    e = evaluate(control_id="M3.12", reviewer_decision={"sufficiency":"full"},
                  claims=[{"claim_id":"C1","grounding_assessment":{"status":"contradicted"}}])
    assert e["posture"] == "defer"
    assert "CONTRADICTED_CLAIM_REMAINS" in e["blockers"]
    with pytest.raises(ValueError, match="DECISION_BLOCKED"):
        enforce(e)


def test_failed_falsification_blocks_full():
    e = evaluate(control_id="M3.12", reviewer_decision={"sufficiency":"full"},
                  probes=[{"probe_id":"P1","status":"resolved","result":"falsified"}])
    assert "FALSIFICATION_PROBE_FAILED" in e["blockers"]


def test_recurring_deficiency_escalates_non_full_decision():
    history=[
      {"control_id":"M3.12","decision":{"sufficiency":"partial"}},
      {"control_id":"M3.12","decision":{"sufficiency":"none"}},
    ]
    e=evaluate(control_id="M3.12", reviewer_decision={"sufficiency":"partial"}, history=history)
    assert e["posture"] == "escalate"
    assert "RECURRING_DEFICIENCY" in e["escalations"]


def test_stable_full_is_adequate():
    e=evaluate(control_id="M3.12", reviewer_decision={"sufficiency":"full"},
               history=[{"control_id":"M3.12","decision":{"sufficiency":"full"}},
                        {"control_id":"M3.12","decision":{"sufficiency":"full"}}])
    assert e["posture"] == "adequate"
    assert e["decision_eligible"] is True


@pytest.fixture
def wired(tmp_path, monkeypatch):
    import events
    import core.cycle as cc
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    class C: id, lib, title, req, owner, maps = "M3.6", "Control Library - MAS", "Validation", "req", "CRO", ""
    monkeypatch.setattr(cc, "_control", lambda cid, framework="": C())
    return cc

def test_cycle_api_blocks_full_when_governed_record_conflicts(wired, tmp_path):
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4}, actor="Yen")
    import events
    s = events.state(cid)
    events.append("challenged", cycle_id=cid, actor="system", control_id="M3.6",
                   framework=s.get("framework", ""), payload={
                       "claim_register": {"claims": [{"claim_id":"C1",
                           "grounding_assessment":{"status":"contradicted"}}]}})
    with pytest.raises(Exception, match="CONTRADICTED_CLAIM_REMAINS"):
        wired.decide(cid, sufficiency="full", maturity=4, reviewer="Yen",
                     reason="the decision is full despite the contradiction")


def test_weak_unresolved_does_not_block_when_strong_is_resolved():
    e = evaluate(
        control_id="M3.12",
        reviewer_decision={"sufficiency": "full"},
        challenges=[
            {"challenge_id": "C-strong", "challenge_strength": "strong", "status": "open", "resolution": "rejected"},
            {"challenge_id": "C-weak", "challenge_strength": "weak", "status": "open"},
        ],
    )
    assert e["challenge_summary"]["strong"] == 1
    assert e["challenge_summary"]["unresolved"] == 1
    assert e["challenge_summary"]["unresolved_strong"] == 0
    assert "STRONG_CHALLENGE_UNRESOLVED" not in e["blockers"]
    assert e["posture"] == "adequate"


def test_unresolved_strong_blocks_even_if_other_challenges_are_resolved():
    e = evaluate(
        control_id="M3.12",
        reviewer_decision={"sufficiency": "full"},
        challenges=[
            {"challenge_id": "C-strong", "challenge_strength": "strong", "status": "pending"},
            {"challenge_id": "C-weak", "challenge_strength": "weak", "status": "open", "resolution": "accepted"},
        ],
    )
    assert e["challenge_summary"]["unresolved_strong"] == 1
    assert "STRONG_CHALLENGE_UNRESOLVED" in e["blockers"]


def test_basis_hash_is_order_independent_for_claims_challenges_and_probes():
    kwargs = dict(
        control_id="M3.12",
        reviewer_decision={"sufficiency": "full", "action": "accept"},
        claims=[
            {"claim_id": "C2", "grounding_assessment": {"status": "supported", "source": "b"}},
            {"claim_id": "C1", "grounding_assessment": {"status": "supported", "source": "a"}},
        ],
        challenges=[
            {"challenge_id": "CH2", "status": "resolved", "resolution": "rejected"},
            {"challenge_id": "CH1", "status": "resolved", "resolution": "accepted"},
        ],
        probes=[
            {"probe_id": "P2", "status": "resolved", "result": "supported"},
            {"probe_id": "P1", "status": "resolved", "result": "supported"},
        ],
    )
    a = evaluate(**kwargs)
    b = evaluate(**{**kwargs, "claims": list(reversed(kwargs["claims"])),
                     "challenges": list(reversed(kwargs["challenges"])),
                     "probes": list(reversed(kwargs["probes"]))})
    assert len(a["basis_hash"]) == 64
    assert a["basis_hash"] == b["basis_hash"]
    assert a["basis"] == b["basis"]


def test_precedent_uses_event_sequence_not_input_order():
    history = [
        {"control_id": "M3.12", "decision": {"sufficiency": "none"}, "decision_event_index": 20},
        {"control_id": "M3.12", "decision": {"sufficiency": "full"}, "decision_event_index": 10},
    ]
    e = evaluate(control_id="M3.12", reviewer_decision={"sufficiency": "full"}, history=history)
    assert e["precedent"]["ratings"] == ["full", "none"]
    assert e["precedent"]["deteriorating"] is True
