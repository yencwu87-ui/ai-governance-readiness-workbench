from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _record_decided_cycle(path: Path, cycle_id: str, control_id: str = "M3.6") -> None:
    import events
    common = {"cycle_id": cycle_id, "actor": "test", "control_id": control_id, "framework": "MAS", "path": path}
    events.append("cycle_started", payload={}, **common)
    events.append("proposed", payload={"proposal": {
        "sufficiency": "full", "proposedMaturity": 4,
        "elementVerdicts": [{"element_id": "e7", "status": "met"}],
    }, "assessment_identity": {"assessment_id": "assessment-1"}}, **common)
    events.append("read", payload={"read": {"sufficiency": "partial", "maturity": 3, "reason": "Scope reconciliation is missing."}}, **common)
    events.append("compared", payload={"diff": {"disagreements": ["e7"]}}, **common)
    events.append("challenged", payload={"challenge_outcome": "substantive", "challenges": [{"challenge_strength": "strong"}]}, **common)
    events.append("decided", payload={"sufficiency": "partial", "maturity": 3, "reason": "Reviewer accepted the scope gap."}, **common)


def test_episodic_lane_reads_prior_decided_event_episodes(tmp_path):
    from governance.retrieval_plane import retrieve_episodes
    log = tmp_path / "events.jsonl"
    _record_decided_cycle(log, "M3-6-history")
    _record_decided_cycle(log, "F1-history", "F1")

    rows = retrieve_episodes("M3.6", "MAS", "independent validation scope", element_ids=["e7"], event_path=log)
    # Same-control history ranks ahead of analogous same-framework history.
    assert rows[0]["episode_id"] == "M3-6-history"
    row = rows[0]
    assert row["assessment_id"] == "assessment-1"
    assert row["prior_assessor_verdict"]["sufficiency"] == "full"
    assert row["challenger_verdict"]["strong_count"] == 1
    assert row["human_decision"]["sufficiency"] == "partial"
    assert row["disagreement"] == ["e7"]


def test_resolver_exposes_independent_lanes_and_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("WB_KNOWLEDGE_MONITOR", str(tmp_path / "knowledge.jsonl"))
    from governance.knowledge_resolver import resolve, typed_context

    class C:
        id = "M3.6"
        lib = "MAS"
        req = "Independent validation must cover the applicable scope."

    bundle = resolve(C(), "validation report and scope reconciliation", role="challenger", force_web=False, element_ids=["e7"])
    plane = bundle["retrieval_plane"]
    assert set(("semantic", "episodic", "procedural", "regulatory")) <= set(plane)
    receipt = bundle["retrieval_receipt"]
    assert set(("semantic", "episodic", "procedural", "regulatory")) <= set(receipt)
    assert receipt["semantic"]["attempted"] is True
    assert receipt["episodic"]["completed"] is True
    assert "effective_sources" in plane["regulatory"]
    rendered = typed_context(bundle)
    assert '"episodic"' in rendered and '"retrieval_receipt"' in rendered
