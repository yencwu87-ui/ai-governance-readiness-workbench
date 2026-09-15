import json
from pathlib import Path

import pytest

import events
from governance import decision_engine


def test_event_digest_is_strict_canonical_and_full_sha(tmp_path):
    p = tmp_path / "events.jsonl"
    e = events.append("cycle_started", cycle_id="c1", actor="a", control_id="M3.6", path=p)
    raw = p.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(raw)
    assert len(obj["sha"]) == 64
    assert events.verify(p)["intact"]
    with pytest.raises(TypeError):
        events._digest({"x": object()})


def test_event_append_validates_identity(tmp_path):
    p = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        events.append("note", cycle_id="", actor="a", path=p)
    with pytest.raises(ValueError):
        events.append("note", cycle_id="c", actor="", path=p)


def test_strong_resolved_does_not_block_for_unrelated_weak_open():
    evaluation = decision_engine.evaluate(
        control_id="M3.6",
        reviewer_decision={"action": "accept", "sufficiency": "full", "maturity": 4, "reason": "supported by evidence"},
        challenges=[
            {"challenge_id": "c-strong", "challenge_strength": "strong", "status": "open", "resolution": "rejected"},
            {"challenge_id": "c-weak", "challenge_strength": "weak", "status": "open"},
        ],
    )
    assert evaluation["challenge_summary"]["strong"] == 1
    assert evaluation["challenge_summary"]["unresolved"] == 1
    assert evaluation["challenge_summary"]["unresolved_strong"] == 0
    assert "STRONG_CHALLENGE_UNRESOLVED" not in evaluation["blockers"]


def test_decided_event_contains_governance_basis(tmp_path):
    p = tmp_path / "events.jsonl"
    cid = "M3-6-test"
    events.append("cycle_started", cycle_id=cid, actor="system", control_id="M3.6", framework="MAS", path=p)
    events.append("read", cycle_id=cid, actor="reviewer", control_id="M3.6", framework="MAS",
                  payload={"read": {"sufficiency": "full", "maturity": 4, "reason": "evidence supports control"}}, path=p)
    from core import cycle
    # Use the engine directly here because control workbook lookup is intentionally outside this unit test.
    ev = decision_engine.evaluate(
        control_id="M3.6",
        reviewer_decision={"action": "accept", "sufficiency": "full", "maturity": 4, "reason": "evidence supports control"},
        reviewer_read={"sufficiency": "full", "maturity": 4},
    )
    decision_engine.enforce(ev)
    events.append("decided", cycle_id=cid, actor="reviewer", control_id="M3.6", framework="MAS",
                  payload={"action": "accept", "sufficiency": "full", "maturity": 4,
                           "governance_decision": ev, "reason": "evidence supports control"}, path=p)
    s = events.state(cid, p)
    assert s["stage"] == "decided"
    assert s["decision"]["governance_decision"]["basis_hash"] == ev["basis_hash"]
    assert s["decision_event_index"] == 2
