from pathlib import Path

from governance.knowledge import load_control_testing, retrieve_control_testing

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "governance" / "knowledge" / "control_testing.yaml"
EXPECTED = {
    "M1.1","M1.2","M1.3","M1.4","M1.5","M2.1","M2.2","M2.3","M2.4",
    "M3.1","M3.2","M3.3","M3.4","M3.5","M3.6","M3.7","M3.8","M3.9",
    "M3.10","M3.11","M3.12","M3.13","M3.14","M3.15","M4.1","M4.2",
    "F1","F2","F3","F4"
}

def test_all_30_mas_controls_have_human_authored_dod_and_toe():
    rows = [r for r in load_control_testing(KB)["controls"] if r.get("framework") == "MAS"]
    assert {r["control_id"] for r in rows} == EXPECTED
    for r in rows:
        testing = r["testing"]
        assert testing["source_status"] == "human_authored_draft"
        assert testing["design"] and testing["design"][0].strip()
        assert testing["operating"] and testing["operating"][0].strip()
        assert "PASS when" in testing["design"][0]
        assert "NOT TESTABLE" in testing["operating"][0]

def test_mas_test_knowledge_is_retrievable():
    for cid in EXPECTED:
        rows = retrieve_control_testing(cid, "MAS", cid, "", limit=1, path=KB)
        assert rows and rows[0]["control_id"] == cid
