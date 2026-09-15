"""WB-040..044 — event store, cycle library, per-role models, replay.

No model, no network, no Streamlit. The assessor and challenger are stubbed at the boundary so
that ordering, blindness, the reason check and the chain properties are asserted rather than
observed.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import events  # noqa: E402
import llm  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "events.jsonl"
    monkeypatch.setattr(events, "LOG", p)
    return p


class _Ctl:
    id, lib, title, req, owner, maps = "M3.6", "Control Library - MAS", "Validation", "req", "CRO", ""


@pytest.fixture
def wired(monkeypatch, log):
    """A cycle library with the workbook lookup and both model calls stubbed."""
    import core.cycle as cc
    monkeypatch.setattr(cc, "_control", lambda cid, fw="": _Ctl())
    return cc


# ---------------- the chain ----------------

def test_events_are_chained_and_verify_clean(log):
    cid = events.new_cycle_id("M3.6")
    for k in ("cycle_started", "read", "decided"):
        events.append(k, cycle_id=cid, actor="yen", control_id="M3.6")
    r = events.verify()
    assert r["intact"] and r["events"] == 3 and r["breaks"] == []


def test_editing_an_event_breaks_the_chain_at_that_event(log):
    cid = events.new_cycle_id("M3.6")
    events.append("cycle_started", cycle_id=cid, actor="yen", control_id="M3.6")
    events.append("read", cycle_id=cid, actor="yen", control_id="M3.6",
                  payload={"read": {"sufficiency": "none"}})
    lines = log.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["payload"]["read"]["sufficiency"] = "full"      # the edit an auditor must catch
    lines[1] = json.dumps(tampered)
    log.write_text("\n".join(lines) + "\n")
    r = events.verify()
    assert not r["intact"]
    assert any("edited" in b["reason"] for b in r["breaks"])


def test_deleting_an_event_breaks_the_chain(log):
    cid = events.new_cycle_id("M3.6")
    for k in ("cycle_started", "read", "decided"):
        events.append(k, cycle_id=cid, actor="yen", control_id="M3.6")
    lines = log.read_text().splitlines()
    log.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not events.verify()["intact"]


def test_an_unknown_event_kind_is_refused(log):
    with pytest.raises(ValueError, match="unknown event kind"):
        events.append("whatever", cycle_id="c1", actor="x")


def test_state_is_a_projection_and_later_events_supersede(log):
    cid = events.new_cycle_id("M3.6")
    events.append("cycle_started", cycle_id=cid, actor="x", control_id="M3.6")
    events.append("read", cycle_id=cid, actor="yen", control_id="M3.6",
                  payload={"read": {"sufficiency": "none"}})
    events.append("read", cycle_id=cid, actor="yen", control_id="M3.6",
                  payload={"read": {"sufficiency": "partial"}})
    s = events.state(cid)
    assert s["read"]["sufficiency"] == "partial"
    assert len(s["history"]) == 3            # the superseded read is still readable


# ---------------- blindness ----------------

def test_the_proposal_is_withheld_until_a_read_is_recorded(wired, monkeypatch, log):
    monkeypatch.setattr("pipeline.propose", lambda c, ev, pdf=None: {"sufficiency": "full", "proposedMaturity": 4})
    monkeypatch.setattr("pipeline.is_error", lambda p: False)
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "evidence"})
    wired.assess(cid)
    assert wired.proposal_for_reviewer(cid) is None          # computed, not shown
    wired.record_read(cid, {"sufficiency": "partial", "maturity": 3}, actor="Yen")
    assert wired.proposal_for_reviewer(cid)["sufficiency"] == "full"


def test_assessing_without_bound_evidence_is_refused(wired, log):
    cid = wired.start("M3.6")
    with pytest.raises(wired.CycleError, match="bind evidence"):
        wired.assess(cid)


def test_a_read_must_name_its_reviewer(wired, log):
    cid = wired.start("M3.6")
    with pytest.raises(wired.CycleError, match="name its reviewer"):
        wired.record_read(cid, {"sufficiency": "full"}, actor="  ")


def test_compare_requires_both_sides(wired, log):
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    with pytest.raises(wired.CycleError, match="nothing to compare"):
        wired.compare_reads(cid)


def test_challenge_requires_a_disagreement(wired, monkeypatch, log):
    monkeypatch.setattr("pipeline.propose", lambda c, ev, pdf=None: {"sufficiency": "full", "proposedMaturity": 4})
    monkeypatch.setattr("pipeline.is_error", lambda p: False)
    monkeypatch.setattr("compare.compare", lambda b, a, c: {"comparable": True, "disagreements": [], "rows": []})
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.assess(cid)
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4}, actor="Yen")
    wired.compare_reads(cid)
    with pytest.raises(wired.CycleError, match="agree on every compared element"):
        wired.challenge(cid)


# ---------------- the reason check on the headless path ----------------

def test_a_hollow_reason_is_refused_headlessly(wired, log):
    """The hollow record — 47 accepts, every reason reading 'accept' — happened because
    agreement was one click. A CLI with no reason check would reproduce it at machine speed."""
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4}, actor="Yen")
    with pytest.raises(wired.CycleError, match="reason refused"):
        wired.decide(cid, sufficiency="full", maturity=4, reason="accept", reviewer="Yen")


def test_a_substantive_reason_is_accepted_and_recorded(wired, log):
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.record_read(cid, {"sufficiency": "partial", "maturity": 3}, actor="Yen")
    d = wired.decide(cid, sufficiency="partial", maturity=3, reviewer="Yen",
                     reason="validation report covers v2 while v3 is deployed, so e2 is not evidenced")
    assert d["sufficiency"] == "partial"
    assert events.state(cid)["stage"] == "decided"


def test_a_decision_must_name_its_reviewer(wired, log):
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4}, actor="Yen")
    with pytest.raises(wired.CycleError, match="name its reviewer"):
        wired.decide(cid, sufficiency="full", maturity=4, reviewer="",
                     reason="the deployed version is covered by the report at line 40")


def test_a_revision_records_what_it_superseded(wired, log):
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "e"})
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4, "reason": "looked complete"}, actor="Yen")
    d = wired.decide(cid, sufficiency="partial", maturity=3, reviewer="Yen",
                     reason="on a second look the report predates the deployed model version")
    assert d["supersedes"]["sufficiency"] == "full"


# ---------------- per-role models ----------------

def test_each_role_can_be_pointed_at_a_different_model(monkeypatch):
    monkeypatch.setenv("WB_MODEL_ELEMENTS", "llama3.2")
    monkeypatch.setenv("WB_MODEL_CHALLENGE", "qwen2.5:14b")
    monkeypatch.delenv("WB_MODEL_ASSESS", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    r = llm.roles_in_use()
    assert r["elements"] == "llama3.2"
    assert r["challenge"] == "qwen2.5:14b"
    assert r["challenge_disagreement"] == "qwen2.5:14b"
    assert r["assess"] == "llama3.1:8b"


def test_model_for_restores_the_previous_model_even_on_failure(monkeypatch):
    import assessor
    monkeypatch.setattr(assessor, "OLLAMA_MODEL", "original", raising=False)
    monkeypatch.setenv("WB_MODEL_ASSESS", "swapped")
    with pytest.raises(RuntimeError):
        with llm.model_for("assess"):
            assert assessor.OLLAMA_MODEL == "swapped"
            raise RuntimeError("boom")
    assert assessor.OLLAMA_MODEL == "original"


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError, match="unknown role"):
        llm.model_name("vibes")


def test_a_failed_call_is_recorded_as_a_failure(tmp_path, monkeypatch):
    m = tmp_path / "metrics.jsonl"
    with pytest.raises(RuntimeError):
        with llm.observe("assess", cycle_id="c1", path=m):
            raise RuntimeError("read timeout")
    s = llm.summary(m)
    assert s["by_role"]["assess"]["failures"] == 1
    assert s["by_role"]["assess"]["failure_rate"] == 1.0


# ---------------- migration ----------------

def test_legacy_import_marks_every_record_as_imported(log):
    blob = {"decisions": {"k1": {"sufficiency": "partial", "reason": "r"}},
            "ai": {"k1": {"sufficiency": "full"}},
            "blind": {"k1": {"sufficiency": "partial"}}}
    made = events.import_legacy(blob)
    assert len(made) == 1
    s = events.state(made[0])
    assert s["decision"]["imported"] is True
    assert all(a == "migration" for _, _, a in s["history"])


def test_the_projection_rebuilds_the_old_shape(log):
    blob = {"decisions": {"M3.6": {"sufficiency": "partial", "reason": "r"}}, "ai": {}, "blind": {}}
    events.import_legacy(blob)
    proj = events.export_projection()
    assert proj["decisions"]["M3.6"]["sufficiency"] == "partial"


# ---------------- the extraction actually happened ----------------

def test_no_module_in_core_imports_streamlit():
    """The test of whether the extraction from app.py worked. If core ever needs Streamlit,
    the workflow has leaked back into the UI and headless running is broken again."""
    for p in (ROOT / "core").rglob("*.py"):
        src = p.read_text()
        assert "import streamlit" not in src and "from streamlit" not in src, p


def test_a_full_cycle_runs_without_a_browser(wired, monkeypatch, log):
    """The whole point: propose, read, compare, challenge, decide, with nothing rendered."""
    monkeypatch.setattr("pipeline.propose", lambda c, ev, pdf=None: {
        "sufficiency": "none", "proposedMaturity": 1,
        "elementVerdicts": [{"element_id": "e1", "status": "not_evidenced", "excerpt": ""}]})
    monkeypatch.setattr("pipeline.is_error", lambda p: False)
    monkeypatch.setattr("compare.compare", lambda b, a, c: {
        "comparable": True, "disagreements": ["e1"], "diff_sha": "abc123",
        "rows": [{"element_id": "e1", "text": "t", "reviewer": "met", "ai": "not_evidenced",
                  "compared": True, "agree": False, "direction": "reviewer_more_generous",
                  "ai_excerpt": ""}],
        "summary": {"n_compared": 1, "n_agree": 0, "n_disagree": 1},
        "rating": {"reviewer": "full", "ai": "none", "agree": False}})
    monkeypatch.setattr("challenge.challenge_disagreement",
                        lambda c, t, b, a, d: {"challenges": [], "challenge_outcome": "no_rebuttal",
                                               "scope_elements": ["e1"], "supports_tally": {}})
    cid = wired.start("M3.6")
    wired.bind_evidence(cid, {"text": "the validation report"})
    wired.assess(cid)
    wired.record_read(cid, {"sufficiency": "full", "maturity": 4,
                            "element_verdicts": [{"element_id": "e1", "status": "met"}]}, actor="Yen")
    diff = wired.compare_reads(cid)
    assert diff["disagreements"] == ["e1"]
    wired.challenge(cid)
    wired.decide(cid, sufficiency="partial", maturity=3, reviewer="Yen",
                 reason="the quoted passage names v2 while the deployed model is v3")
    s = events.state(cid)
    assert s["stage"] == "decided"
    assert s["decision"]["element_diff"]["diff_sha"] == "abc123"
    assert s["decision"]["revised_after_challenge"] is True
    assert events.verify()["intact"]
