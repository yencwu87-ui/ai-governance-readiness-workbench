"""GE-110b.1/.2 — per-case provenance, and a governed refusal that is not a crash."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.label_provenance import INHERITED, PER_CASE, migrate, summary, validate, justification_for

DOC = {"control": "X", "elements": [
    {"id": "e1", "text": "t1", "a": "Y", "b": "N", "c": "N",
     "where": "an element-level note", "decided_by": "claude-unconfirmed"}]}


def test_migration_creates_one_record_per_case_element_pair():
    m = migrate(DOC, today="2026-09-14")
    assert len(m["judgements"]) == 3
    assert {j["case"] for j in m["judgements"]} == {"a", "b", "c"}


def test_verdicts_are_copied_because_they_are_real():
    m = migrate(DOC, today="2026-09-14")
    by_case = {j["case"]: j["verdict"] for j in m["judgements"]}
    assert by_case == {"a": "Y", "b": "N", "c": "N"}


def test_a_carried_over_note_is_marked_inherited_not_upgraded():
    """The repair must not hide the defect it repairs."""
    m = migrate(DOC, today="2026-09-14")
    assert all(j["provenance"] == INHERITED for j in m["judgements"])
    assert summary(m)["fully_argued"] is False


def test_migration_does_not_upgrade_authority():
    m = migrate(DOC, today="2026-09-14")
    assert all(j["labelled_by"] == "claude-unconfirmed" for j in m["judgements"])


def test_a_real_per_case_judgement_is_recorded_as_such():
    doc = dict(DOC)
    doc["judgements"] = [{"case": "a", "element": "e1", "verdict": "Y",
                          "justification": "section 5 names the independent validator",
                          "provenance": PER_CASE, "source_refs": ["X_a.md#5"],
                          "labelled_by": "wu yenching", "labelled_at": "2026-09-14"}]
    m = migrate(doc, today="2026-09-14")
    text, prov = justification_for(m, "a", "e1")
    assert prov == PER_CASE and "independent validator" in text
    # The other two cases still migrate as inherited.
    assert justification_for(m, "b", "e1")[1] == INHERITED


def test_migration_is_idempotent():
    once = migrate(DOC, today="2026-09-14")
    twice = migrate(once, today="2026-09-14")
    assert len(once["judgements"]) == len(twice["judgements"])


def test_validate_reports_and_does_not_block():
    findings = validate(migrate(DOC, today="2026-09-14"))
    assert any(f["code"] == "INHERITED_JUSTIFICATION" for f in findings)
    assert all("executable" not in f for f in findings)


def test_the_real_corpora_carry_judgement_records_now():
    # M3.6 grew from 42 to 94 when the adjudicated d/e/f/g set was ingested. The per-case
    # assertion below is scoped to M3.12, which is still migration-only; M3.6's calibration
    # scope is covered in test_ge110b_calibration_invariant.py.
    for ctl, n in (("M3.6", 94), ("M3.12", 18)):
        p = ROOT / "eval" / "corpus" / ctl / "elements.yaml"
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert doc.get("judgements"), f"{ctl} has no judgement records"
        assert len(doc["judgements"]) == n
        # None of them argued yet — that is the honest state, and it is pinned so a later
        # change cannot quietly claim otherwise without doing the labelling.
        if ctl == "M3.12":
            assert summary(doc)["per_case"] == 0


def test_the_rendered_cell_marks_an_inherited_note():
    p = ROOT / "eval" / "corpus" / "M3.12" / "LABELS.md"
    if not p.exists():
        pytest.skip("M3.12 labels not present")
    assert "↩ element-level" in p.read_text(encoding="utf-8")


# ------------------------------------------------------------------ the refusal is a result

def test_a_blocked_contract_does_not_crash_the_caller():
    """M1.1 killed a bulk run: ContractInvalid reached the top of the Streamlit script.

    Raising at the engine boundary is right and stays. The caller treating a governed refusal
    as a crash is what was wrong — an unassessable contract is a result, like NOT_TESTABLE.
    """
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    fn = src[src.index("def _ensure_cycle("): src.index("def _ensure_cycle(") + 2200]
    assert "except ContractInvalid" in fn
    assert "contract_blocked" in fn


def test_the_bulk_run_skips_before_calling_the_model():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "skipped.append(c.id)" in src
    assert "CONTRACT INVALID" in src


def test_the_cycle_and_evidence_survive_a_refusal(tmp_path, monkeypatch):
    import glob
    monkeypatch.setenv("WB_EVENTS", str(tmp_path / "e.jsonl"))
    for m in ("events", "core.cycle"):
        sys.modules.pop(m, None)
    import events, core.cycle as cyc, playbook
    from governance.contract_integrity import ContractInvalid
    idx = playbook.load_controls(glob.glob(str(ROOT / "data" / "*.xlsx"))[0])
    # Was hardcoded to M1.1, which is no longer invalid — the decomposition repairs fixed its
    # cross-control contamination. Pinning a test to a specific defect makes the test fail when
    # the defect is fixed, which reads as a regression and is the opposite of one. Pick whatever
    # control is currently invalid instead, and skip honestly if the library is clean.
    from governance.contract_integrity import status_for_control
    c = next((x for lib in idx.values() for x in lib
              if not status_for_control(x).get("executable", True)), None)
    if c is None:
        pytest.skip("no control currently fails contract integrity — nothing to refuse")
    cid = cyc.start(c.id, framework=c.lib, actor="t")
    cyc.bind_evidence(cid, {"text": "--- Source: a.md ---\nx"}, actor="t")
    with pytest.raises(ContractInvalid):
        cyc.record_proposal(cid, {"sufficiency": "partial", "proposedMaturity": 2, "model": "m"})
    kinds = {e["kind"] for e in events.cycle(cid)}
    assert kinds == {"cycle_started", "evidence_bound"}, "evidence must survive the refusal"
