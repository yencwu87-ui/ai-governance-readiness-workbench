"""WB-050/051/057 — the run, drift, and the work queue.

Puppet's value is not that it knows the desired state; it is that it tells you where reality has
moved away from it. These pin the three properties that make that tractable here: silence on an
unchanged control, refusal to attribute a moved yardstick to the estate, and a queue that ranks
reviewer attention rather than listing everything.

No model, no network, no filesystem scan — `compare` is pure and the run fixtures are literals.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import drift as D  # noqa: E402
import events  # noqa: E402
import work_queue as Q  # noqa: E402


def run(run_id, *, controls, evidence, outcomes=None, catalog_sha="cat1"):
    return {"run_id": run_id, "ts": f"2026-09-1{run_id[-1]}T00:00:00+00:00",
            "catalog_sha": catalog_sha, "catalog": controls, "evidence": evidence,
            "outcomes": outcomes or {}, "trigger": "test"}


def ctl(cid, req="r1", con="c1", fw="Control Library - MAS"):
    return {"control_id": cid, "framework": fw, "requirement_sha": req, "contract_sha": con}


def ev(matched=3, digest="d1", sources=("/a.md",)):
    return {"matched": matched, "digest": digest, "sources": list(sources)}


# ---------------- silence ----------------

def test_an_unchanged_control_is_not_reported(): 
    a = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    d = D.compare(a, b)
    assert d["changed"] == 0 and d["silent"] == 1
    out = D.render(d)
    assert "Nothing moved" in out
    assert "expected result of a run, not a failure to look" in out


def test_unchanged_controls_are_excluded_from_the_report_body():
    a = run("r1", controls=[ctl("M1.1"), ctl("M3.6")],
            evidence={"M1.1": ev(), "M3.6": ev()})
    b = run("r2", controls=[ctl("M1.1"), ctl("M3.6")],
            evidence={"M1.1": ev(), "M3.6": ev(digest="d2")})
    out = D.render(D.compare(a, b))
    assert "M3.6" in out and "M1.1" not in out


# ---------------- the estate moved ----------------

def test_changed_evidence_is_detected_and_sourced():
    a = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev(sources=("/old.md",))})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev(digest="d2", sources=("/new.md",))})
    d = D.compare(a, b)
    row = d["rows"][0]
    assert "evidence_changed" in row["classes"]
    assert any("/new.md" in n for n in row["notes"])
    assert row["needs_reassessment"]


def test_lost_evidence_is_a_finding_not_a_silence():
    """A control that had evidence last week and has none now is more urgent than one that
    never had any."""
    a = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev(matched=3)})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev(matched=0, digest=None)})
    row = D.compare(a, b)["rows"][0]
    assert "evidence_lost" in row["classes"]
    assert "evidence_lost" in D.CLASSES[:2]      # ranked above everything but nothing


def test_newly_covered_is_distinguished_from_changed():
    a = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev(matched=0, digest=None)})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    cls = D.compare(a, b)["rows"][0]["classes"]
    assert "newly_covered" in cls and "evidence_changed" not in cls


# ---------------- the yardstick moved ----------------

def test_a_changed_requirement_is_not_attributed_to_the_estate():
    a = run("r1", controls=[ctl("M3.6", req="old")], evidence={"M3.6": ev()},
            outcomes={"M3.6": {"sufficiency": "full", "cycle_id": "c1"}})
    b = run("r2", controls=[ctl("M3.6", req="new")], evidence={"M3.6": ev()},
            outcomes={"M3.6": {"sufficiency": "none", "cycle_id": "c2"}}, catalog_sha="cat2")
    d = D.compare(a, b)
    row = d["rows"][0]
    assert "requirement_changed" in row["classes"]
    # the outcome moved full -> none, and drift refuses to call that a regression
    assert row["outcome_direction"] is None
    assert any("different question" in n for n in row["notes"])
    assert "not comparable on outcome" in D.render(d)


def test_an_outcome_change_under_a_stable_requirement_gets_a_direction():
    a = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev()},
            outcomes={"M3.6": {"sufficiency": "full", "cycle_id": "c1"}})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev()},
            outcomes={"M3.6": {"sufficiency": "partial", "cycle_id": "c2"}})
    assert D.compare(a, b)["rows"][0]["outcome_direction"] == "regressed"


# ---------------- scope ----------------

def test_controls_entering_and_leaving_scope_are_both_reported():
    a = run("r1", controls=[ctl("M1.1")], evidence={"M1.1": ev()})
    b = run("r2", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    d = D.compare(a, b)
    by = {r["control_id"]: r["classes"] for r in d["rows"]}
    assert "control_removed" in by["M1.1"] and "control_added" in by["M3.6"]


def test_the_reassessment_queue_is_ordered_by_urgency():
    a = run("r1", controls=[ctl("M1.1"), ctl("M3.6")],
            evidence={"M1.1": ev(), "M3.6": ev()})
    b = run("r2", controls=[ctl("M1.1"), ctl("M3.6")],
            evidence={"M1.1": ev(digest="d2"), "M3.6": ev(matched=0, digest=None)})
    assert D.reassessment_queue(D.compare(a, b))[0] == "M3.6"   # evidence lost outranks changed


# ---------------- the work queue ----------------

@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    return tmp_path / "events.jsonl"


def test_a_control_with_evidence_and_no_reading_is_queued(log):
    r = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    rows = Q.build(r, None)
    assert rows[0]["control_id"] == "M3.6"
    assert rows[0]["top_reason"] == "never_assessed"


def test_a_decided_control_with_unchanged_evidence_is_not_queued(log):
    cid = events.new_cycle_id("M3.6")
    events.append("cycle_started", cycle_id=cid, actor="s", control_id="M3.6")
    events.append("decided", cycle_id=cid, actor="Yen", control_id="M3.6",
                  payload={"sufficiency": "partial", "reason": "r"})
    r = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    assert Q.build(r, None) == []


def test_drift_outranks_a_never_assessed_control(log):
    r = run("r2", controls=[ctl("M1.1"), ctl("M3.6")],
            evidence={"M1.1": ev(), "M3.6": ev(digest="d2")})
    d = {"rows": [{"control_id": "M3.6", "framework": "Control Library - MAS",
                   "classes": ["evidence_changed"], "notes": ["changed content"]}]}
    rows = Q.build(r, d)
    assert rows[0]["control_id"] == "M3.6" and rows[0]["top_reason"] == "drift"


def test_an_empty_queue_says_why_rather_than_printing_nothing(log):
    out = Q.render([])
    assert "Nothing is queued" in out and "not a failure to look" in out


def test_the_queue_warns_that_reading_quality_is_the_measurement_quality(log):
    r = run("r1", controls=[ctl("M3.6")], evidence={"M3.6": ev()})
    out = Q.render(Q.build(r, None))
    assert "ten read properly" in out
