from governance.outcomes import crosswalk_validation, evaluate_outcome, capability_ids


def test_capability_catalog_covers_crosswalk_and_outcomes():
    assert not crosswalk_validation(), crosswalk_validation()
    assert "SDLC.BRANCH_PROTECTION" in capability_ids()


def test_dangling_crosswalk_fails_closed(monkeypatch):
    import governance.outcomes as out
    original = out.load_crosswalk
    bad = original()
    bad["mappings"] = list(bad["mappings"]) + [{
        "framework": "MAS", "control_id": "M9.99", "element_id": "e1",
        "maps_to": {"outcomes": ["OVS-CHANGE-01"], "capabilities": ["SDLC.BRANCH_PROTECTION"]},
    }]
    monkeypatch.setattr(out, "load_crosswalk", lambda: bad)
    result = out.evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key={})
    assert result["posture"] == "defer"
    assert any(e["code"] == "CROSSWALK_DANGLING_POINTER" for e in result["errors"])


def test_v08_hard_blocker_overrides_other_full_items():
    decisions = {
        "MAS::M3.12": {"sufficiency": "full", "governance_decision": {"decision_eligible": True}},
        "MGF::D2.2": {"sufficiency": "full", "governance_decision": {"decision_eligible": False, "blockers": ["STRONG_CHALLENGE_UNRESOLVED"]}},
        "MAS::M3.8": {"sufficiency": "full", "governance_decision": {"decision_eligible": True}},
    }
    result = evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key=decisions)
    assert result["posture"] == "defer"
    assert result["posture_code"] == "STRONG_CHALLENGE_UNRESOLVED"


def test_next_actions_are_stably_sorted():
    decisions = {}
    a = evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key=decisions)
    b = evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key=decisions)
    assert a["next_actions"] == b["next_actions"]


def test_framework_namespace_is_canonicalized_for_decisions():
    decisions = {
        "MGF Agentic::D2.2": {"sufficiency": "full"},
        "MAS::M3.12": {"sufficiency": "full"},
    }
    # The public evaluator accepts legacy/raw event keys defensively, but authoritative_decisions
    # itself writes canonical keys. This test exercises the normalized lookup path directly.
    import governance.outcomes as out
    normalized = {out._ck(k.split("::", 1)[0], k.split("::", 1)[1]): v for k, v in decisions.items()}
    assert normalized["MGF::D2.2"]["sufficiency"] == "full"
    result = out.evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key=normalized)
    assert any(x["framework"] == "MGF" and x["control_id"] == "D2.2" and x["status"] == "full" for x in result["mapped_items"])


def test_capability_blocked_is_not_contradicted():
    import governance.outcomes as out
    decisions = {
        "MGF::D2.2": {
            "sufficiency": "full",
            "governance_decision": {
                "decision_eligible": False,
                "blockers": ["STRONG_CHALLENGE_UNRESOLVED"],
            },
        },
    }
    cap = out.evaluate_capability(
        "SDLC.APPROVER_NOT_AUTHOR",
        mappings=out.load_crosswalk().get("mappings", []),
        decisions_by_control_key=decisions,
    )
    assert cap["status"] == "blocked"
    assert cap["status"] != "contradicted"


def test_capability_status_is_global_not_outcome_relative():
    import governance.outcomes as out
    decisions = {"MAS::M3.12": {"sufficiency": "full"}}
    caps = out.evaluate_capabilities_global(decisions_by_control_key=decisions)
    assert "SDLC.APPROVER_NOT_AUTHOR" in caps
    assert any(i["control_id"] == "M3.12" for i in caps["SDLC.APPROVER_NOT_AUTHOR"]["items"])


def test_next_action_includes_evidence_modes():
    import governance.outcomes as out
    result = out.evaluate_outcome("OVS-CHANGE-01", decisions_by_control_key={})
    assert any("evidence mode:" in action for action in result["next_actions"])


def test_event_write_boundary_canonicalizes_mgf_and_mas(tmp_path):
    import events
    p = tmp_path / "events.jsonl"
    e1 = events.append("cycle_started", cycle_id="c1", actor="tester", control_id="D2.2", framework="MGF Agentic", path=p)
    e2 = events.append("cycle_started", cycle_id="c2", actor="tester", control_id="M3.12", framework="MAS Governance", path=p)
    assert e1["framework"] == "MGF"
    assert e2["framework"] == "MAS"
