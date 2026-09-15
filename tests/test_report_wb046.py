"""WB-046 — the workpaper is generated from the record, never written around it.

These assert the properties that make the document defensible rather than merely presentable:
absence is shown rather than omitted, a broken chain leads the page, and an agreement rate over
nothing is withheld rather than printed as zero.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import events  # noqa: E402
import report  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    return tmp_path / "events.jsonl"


def _decided(control="M3.6", *, summary=None, disagreements=(), challenged=False, imported=False):
    cid = events.new_cycle_id(control)
    fw = "Control Library - MAS"
    events.append("cycle_started", cycle_id=cid, actor="system", control_id=control, framework=fw)
    events.append("evidence_bound", cycle_id=cid, actor="system", control_id=control, payload={"text": "e"})
    events.append("proposed", cycle_id=cid, actor="assessor", control_id=control,
                  payload={"proposal": {"sufficiency": "none", "proposedMaturity": 1}})
    events.append("read", cycle_id=cid, actor="Yen", control_id=control,
                  payload={"read": {"sufficiency": "full", "maturity": 4}})
    payload = {"sufficiency": "partial", "maturity": 3, "assessor_shown": True,
               "reason": "the report covers v2 while v3 is deployed", "challenged": challenged,
               "imported": imported}
    if summary:
        payload["element_diff"] = {"summary": summary, "disagreements": list(disagreements)}
    events.append("decided", cycle_id=cid, actor="Yen", control_id=control, payload=payload)
    return cid


def test_an_open_cycle_is_reported_not_omitted(log):
    _decided()
    cid = events.new_cycle_id("M1.1")
    events.append("cycle_started", cycle_id=cid, actor="system", control_id="M1.1")
    d = report.gather()
    assert d["counts"]["open"] == 1
    md = report.render_markdown(d)
    assert "Not concluded" in md
    assert "M1.1" in md
    # The distinction that matters: unassessed is not the same as assessed and adequate.
    assert "not the same as assessed and found adequate" in md


def test_agreement_is_withheld_when_nothing_was_compared(log):
    _decided(summary=None)
    d = report.gather()
    assert d["counts"]["element_agreement"] is None
    md = report.render_markdown(d)
    assert "absence of measurement, not a finding of agreement" in md
    assert "0%" not in md            # a zero here would read as a finding


def test_agreement_is_reported_when_elements_were_compared(log):
    _decided(summary={"n_compared": 4, "n_agree": 3})
    d = report.gather()
    assert d["counts"]["element_agreement"] == 0.75
    assert "75%" in report.render_markdown(d)


def test_a_broken_chain_leads_the_document(log):
    _decided()
    lines = log.read_text().splitlines()
    import json
    bad = json.loads(lines[-1])
    bad["payload"]["sufficiency"] = "full"        # the edit a workpaper must not paper over
    lines[-1] = json.dumps(bad)
    log.write_text("\n".join(lines) + "\n")
    md = report.render_markdown(report.gather())
    assert md.index("Record integrity — FAILED") < md.index("Scope and coverage")
    assert "not evidence until this is resolved" in md


def test_disagreements_get_their_own_section(log):
    _decided(summary={"n_compared": 3, "n_agree": 1}, disagreements=("e2", "e3"), challenged=True)
    md = report.render_markdown(report.gather())
    assert "Where the reviewer and the assessor differed" in md
    assert "e2, e3" in md
    assert "after challenge" in md


def test_imported_cycles_are_flagged_as_weaker_evidence(log):
    _decided(imported=True)
    md = report.render_markdown(report.gather())
    assert "reconstructed from a mutable file" in md


def test_every_decision_carries_its_reviewer_reason_and_cycle_id(log):
    cid = _decided()
    md = report.render_markdown(report.gather())
    assert "Yen" in md and "the report covers v2" in md and cid in md


def test_scope_can_be_restricted_to_one_control(log):
    _decided("M3.6")
    _decided("M3.12")
    d = report.gather("M3.6")
    assert {r["control_id"] for r in d["rows"]} == {"M3.6"}


def test_the_basis_of_preparation_states_that_no_model_set_a_rating(log):
    _decided()
    assert "No rating in this document was set by a model." in report.render_markdown(report.gather())
