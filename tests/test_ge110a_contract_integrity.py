"""GE-110a — a corrupted contract is not assessable."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.contract_integrity import (INVALID, VALID, ContractInvalid, assert_executable,
                                           summarise, validate_contract)

GOOD = {"control_id": "M1.2", "framework": "MAS",
        "elements": [{"id": "e1", "text": "The board approves the AI risk appetite annually."}]}
GOOD_ARTS = ["AI use policy", "Board minutes"]


def test_a_sound_contract_is_executable():
    r = validate_contract(GOOD, artefacts=GOOD_ARTS)
    assert r["status"] == VALID and r["executable"] is True
    assert "valid" in summarise(r).lower()


def test_duplicate_element_ids_block():
    c = dict(GOOD, elements=[{"id": "e1", "text": "a"}, {"id": "e1", "text": "b"}])
    r = validate_contract(c, artefacts=GOOD_ARTS)
    assert r["status"] == INVALID
    assert any(f["code"] == "DUPLICATE_ELEMENT_ID" for f in r["findings"])


def test_a_control_carrying_another_controls_element_set_blocks():
    """M1.1 carrying M3.6's elements, the defect that motivated the check."""
    m36 = {"control_id": "M3.6", "elements": [{"id": "e1", "text": "Evaluation measures are "
                                                                  "defined before testing."}]}
    m11 = {"control_id": "M1.1", "elements": [{"id": "e1", "text": "Evaluation measures are "
                                                                  "defined before testing."}]}
    r = validate_contract(m11, artefacts=GOOD_ARTS, others=[m36])
    assert r["status"] == INVALID
    f = next(f for f in r["findings"] if f["code"] == "CROSS_CONTROL_ELEMENT_CONTAMINATION")
    assert f["other_control"] == "M3.6"


def test_two_controls_sharing_one_obligation_is_not_contamination():
    """Compared as a set. Overlap is normal; carrying the whole decomposition is not."""
    a = {"control_id": "A", "elements": [{"id": "e1", "text": "Records are retained for audit."},
                                         {"id": "e2", "text": "An owner is named."}]}
    b = {"control_id": "B", "elements": [{"id": "e1", "text": "Records are retained for audit."}]}
    r = validate_contract(b, artefacts=GOOD_ARTS, others=[a])
    assert r["executable"] is True


def test_a_requirement_sentence_in_the_artefact_column_blocks():
    r = validate_contract(GOOD, artefacts=[
        "Post-implementation verification and closure or exception handling are required."])
    assert r["status"] == INVALID
    assert any(f["code"] == "REQUIREMENT_AS_ARTEFACT" for f in r["findings"])


def test_a_real_artefact_name_passes():
    for name in ("Change records", "Board mandate; approved framework",
                 "Committee terms of reference", "Risk materiality assessment record"):
        r = validate_contract(GOOD, artefacts=[name])
        assert r["executable"] is True, name


def test_a_known_tool_output_as_source_blocks():
    r = validate_contract(GOOD, artefacts=GOOD_ARTS,
                          source_path="data/playbook_assessed_2026-09-14.xlsx")
    assert r["status"] == INVALID
    assert any(f["code"] == "GENERATED_SOURCE_IN_AUTHORITATIVE_PATH" for f in r["findings"])


def test_an_ambiguous_filename_warns_rather_than_blocks():
    """`_audited` reads both ways. Asserting it is generated blocked all 195 controls on a guess."""
    r = validate_contract(GOOD, artefacts=GOOD_ARTS,
                          source_path="data/Playbook_v0.5.2_requirement_elements_audited.xlsx")
    assert r["executable"] is True
    assert any(f["code"] == "SOURCE_PROVENANCE_UNDECLARED" for f in r["findings"])


def test_placeholder_only_evidence_blocks():
    r = validate_contract(GOOD, artefacts=["as applicable", "TBD"])
    assert r["status"] == INVALID
    assert any(f["code"] == "PLACEHOLDER_EVIDENCE_ONLY" for f in r["findings"])


def test_no_declared_evidence_warns_but_does_not_block():
    """Most of the library declares nothing. Blocking 165 controls would stop all work."""
    r = validate_contract(GOOD, artefacts=[])
    assert r["executable"] is True
    assert any(f["code"] == "NO_DECLARED_EVIDENCE" for f in r["findings"])


def test_an_element_that_is_verbatim_a_test_step_blocks():
    c = {"control_id": "D1.3",
         "elements": [{"id": "e2", "text": "Sample boundary events in the period: blocks, "
                                           "referrals and overrides."}],
         "test_of_operating_effectiveness": [
             {"id": "O3", "text": "Sample boundary events in the period: blocks, referrals "
                                  "and overrides."}],
         "test_provenance": "ToD/ToE do not create requirement obligations."}
    r = validate_contract(c, artefacts=GOOD_ARTS)
    assert r["status"] == INVALID
    assert any(f["code"] == "WRITE_BACK_PROVENANCE_MISMATCH" for f in r["findings"])


def test_warnings_never_escalate_into_a_block_on_volume():
    """A count of warnings that eventually blocks is a threshold nobody chose."""
    r = validate_contract(GOOD, artefacts=[],
                          source_path="data/x_audited.xlsx")
    assert r["warning_count"] >= 2
    assert r["executable"] is True


def test_assert_executable_raises_rather_than_returning_a_status_nobody_reads():
    with pytest.raises(ContractInvalid) as exc:
        assert_executable(GOOD, artefacts=["Records are retained for audit purposes."])
    assert "CONTRACT_INVALID" in str(exc.value)
    assert exc.value.report["error_count"] >= 1


def test_the_verdict_is_not_warning_then_continue():
    """The design decision, pinned: an unassessable contract does not produce an assessment."""
    r = validate_contract(GOOD, artefacts=["Records are retained for audit purposes."])
    assert r["executable"] is False
    assert r["status"] == "CONTRACT_INVALID"


# ------------------------------------------------------------------ the gate is on the road

def _real_control(control_id):
    import glob
    import playbook
    idx = playbook.load_controls(glob.glob(str(ROOT / "data" / "*.xlsx"))[0])
    return next(c for lib in idx.values() for c in lib if c.id == control_id)


def _fresh_cycle(tmp_path, monkeypatch, control):
    monkeypatch.setenv("WB_EVENTS", str(tmp_path / "events.jsonl"))
    for m in ("events", "core.cycle"):
        sys.modules.pop(m, None)
    import core.cycle as cyc
    cid = cyc.start(control.id, framework=control.lib, actor="t")
    cyc.bind_evidence(cid, {"text": "--- Source: a.md ---\nbody"}, actor="t")
    return cyc, cid


def test_record_proposal_refuses_an_invalid_contract(tmp_path, monkeypatch):
    """The closure the reviewer flagged: a validator nothing calls is not a gate.

    M3.6 fails integrity against the workbook in `data/` — cross-control contamination plus
    requirement sentences in the artefact column. The UI's asynchronous write path must refuse
    it, not only `assess()`, because GE-109 established that the UI writes proposals itself.
    """
    c = _real_control("M3.6")
    cyc, cid = _fresh_cycle(tmp_path, monkeypatch, c)
    with pytest.raises(ContractInvalid) as exc:
        cyc.record_proposal(cid, {"sufficiency": "partial", "proposedMaturity": 2, "model": "m"})
    assert exc.value.report["control_id"] == "M3.6"
    assert exc.value.report["error_count"] > 0


def test_a_valid_contract_still_records(tmp_path, monkeypatch):
    """The gate must not be a blanket refusal."""
    c = _real_control("M1.2")
    cyc, cid = _fresh_cycle(tmp_path, monkeypatch, c)
    cyc.record_proposal(cid, {"sufficiency": "partial", "proposedMaturity": 2, "model": "m"})
    import events
    assert any(e["kind"] == "proposed" for e in events.cycle(cid))


def test_both_write_paths_carry_the_gate():
    """`assess` runs the assessor and writes; `record_proposal` writes what the UI computed.

    A guard on one is the `check_bundle_unchanged` mistake again — it lived inside `assess()`,
    which the UI never calls, and protected nothing for months.
    """
    src = (ROOT / "core" / "cycle.py").read_text(encoding="utf-8")
    for fn in ("def assess(", "def record_proposal("):
        body = src[src.index(fn): src.index(fn) + 2000]
        assert "assert_contract_executable(" in body, f"{fn} is not gated"


def test_the_service_seam_exists_so_the_ui_never_assembles_a_contract():
    import core.cycle as cyc
    assert "contract_status" in cyc.__all__
    assert "assert_contract_executable" in cyc.__all__


def test_the_ui_does_not_contain_the_validity_rules():
    """The app renders a verdict; it must not decide one."""
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    for leaked in ("REQUIREMENT_AS_ARTEFACT\" ==", "_PREDICATE", "GENERATED_PATTERNS",
                   "check_requirement_used_as_artefact", "validate_contract("):
        assert leaked not in app_src, f"validation logic leaked into app.py: {leaked}"
    assert "contract_status(" in app_src, "the app should ask the service for a status"
