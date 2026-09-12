from pathlib import Path

from governance.knowledge import (
    load_control_testing,
    retrieve_control_testing,
    validate_control_testing,
    format_control_testing_context,
)

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "governance" / "knowledge" / "control_testing.yaml"


def test_control_testing_kb_has_all_playbook_controls():
    data = load_control_testing(KB)
    assert data["control_count"] == 195
    assert len(data["controls"]) == 195


def test_control_testing_kb_validates_cleanly():
    assert validate_control_testing(KB) == []


def test_mas_m312_testing_knowledge_is_retrievable():
    rows = retrieve_control_testing("M3.12", "MAS", "change management", "approval verification", limit=1, path=KB)
    assert rows and rows[0]["control_id"] == "M3.12"
    assert rows[0]["framework"] == "MAS"
    assert rows[0]["testing"]["source_status"] == "human_authored_draft"
    ctx = format_control_testing_context(rows)
    assert "M3.12" in ctx
    assert "Test of Operating Effectiveness" in ctx


def test_testing_knowledge_does_not_claim_authority_when_derived():
    rows = retrieve_control_testing("D1.3", "MGF Agentic", "agent limits", "", limit=1, path=KB)
    assert rows and rows[0]["authority_tier"] == "example"
    assert rows[0]["testing"]["source_status"] == "draft_derived"
