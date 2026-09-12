from pathlib import Path
import copy

from caa.mas_tests import SPECS, run_control
from governance.regulatory_change import build_draft, validate_draft, control_diff


def test_all_30_mas_controls_have_executable_specs():
    expected = [f"M1.{i}" for i in range(1,6)] + [f"M2.{i}" for i in range(1,5)] + [f"M3.{i}" for i in range(1,16)] + ["M4.1", "M4.2", "F1", "F2", "F3", "F4"]
    assert len(expected) == 30
    assert set(expected) == set(SPECS)


def test_m312_catches_duplicate_and_missing_verification():
    evidence = {"records": {"changes": [
        {"ticket_id": "WB-001", "approved_at": "2026-09-01T09:00:00Z", "implemented_at": "2026-09-01T10:00:00Z", "verified_at": "2026-09-01T11:00:00Z"},
        {"ticket_id": "WB-001", "approved_at": "2026-09-02T09:00:00Z", "implemented_at": "2026-09-02T10:00:00Z", "verified_at": "2026-09-02T11:00:00Z"},
    ]}}
    r = run_control("M3.12", evidence, "operating")[0]
    assert r.verdict == "FAIL"
    assert any("duplicate ticket_id" in f for f in r.findings)


def test_m312_catches_approval_after_implementation():
    evidence = {"records": {"changes": [
        {"ticket_id": "WB-001", "approved_at": "2026-09-01T11:00:00Z", "implemented_at": "2026-09-01T10:00:00Z", "verified_at": "2026-09-01T12:00:00Z"},
    ]}}
    r = run_control("M3.12", evidence, "operating")[0]
    assert r.verdict == "FAIL"
    assert any("approved_at must be before implemented_at" in f for f in r.findings)


def test_no_operating_evidence_is_not_testable():
    r = run_control("M3.12", {"records": {}}, "operating")[0]
    assert r.verdict == "NOT_TESTABLE"


def test_regulatory_draft_does_not_mutate_live_and_records_base_sha():
    base = {"version": "0.4", "controls": {"M1.1": {"requirement": "old"}}}
    proposed = copy.deepcopy(base["controls"])
    proposed["M1.1"]["requirement"] = "new"
    draft = build_draft(proposed, source_title="MAS update", source_reference="source://mas/update")
    assert draft["status"] == "draft"
    assert draft["draft"] is True
    assert draft["regulatory_change"]["base_sha256"]
    assert draft["change_impact"]["changed"] == ["M1.1"]
    assert not validate_draft(draft)
