"""WB-021: a failed assessor call is not a rating.

Run from repo/ with the venv active:
    pytest test_propose_error_wb021.py -q
"""
from dataclasses import dataclass

import pipeline


@dataclass
class FakeControl:
    key: str = "MAS::M3.6"
    id: str = "M3.6"
    title: str = "Evaluation, testing & independent validation"
    lib: str = "MAS"
    owner: str = "Model Owner + InfoSec"
    req: str = "Validation and test reports"
    maps: str = ""


def test_failed_call_produces_no_rating(monkeypatch):
    def boom(*a, **kw):
        raise TimeoutError("Read timed out. (read timeout=300)")
    monkeypatch.setattr(pipeline, "assess", boom)

    out = pipeline.propose(FakeControl(), {"text": "some evidence"})
    assert pipeline.is_error(out)
    assert "sufficiency" not in out          # the whole point: no rating exists
    assert "proposedMaturity" not in out
    assert "TimeoutError" in out["error"]


def test_successful_call_is_marked_ok(monkeypatch):
    monkeypatch.setattr(pipeline, "assess",
                        lambda *a, **kw: {"sufficiency": "partial", "proposedMaturity": 3})
    out = pipeline.propose(FakeControl(), {"text": "some evidence"})
    assert not pipeline.is_error(out)
    assert out["status"] == "ok"
    assert out["sufficiency"] == "partial"


def test_assessor_status_is_not_overwritten(monkeypatch):
    """setdefault, not assignment - a status the assessor set survives."""
    monkeypatch.setattr(pipeline, "assess",
                        lambda *a, **kw: {"sufficiency": "none", "status": "degraded"})
    assert pipeline.propose(FakeControl(), {"text": "x"})["status"] == "degraded"


def test_gap_analysis_shows_the_failure_not_a_finding():
    c = FakeControl()
    rows = pipeline.gap_analysis([c], {c.key: {"status": "error", "error": "TimeoutError: x"}}, {})
    assert len(rows) == 1
    assert rows[0]["Finding"] == "not assessed — the assessor call failed"
    assert rows[0]["Priority"] == 0


def test_reviewer_decision_over_an_errored_proposal_still_records():
    """A reviewer may assess it themselves. The decision stands; the AI columns stay empty."""
    c = FakeControl()
    d = pipeline.record_decision({"status": "error"}, "partial", 2, "assessed by hand", "yenching")
    rows = pipeline.gap_analysis([c], {c.key: {"status": "error"}}, {c.key: d})
    assert rows[0]["Finding"].startswith("partial")
    assert d["aiSufficiency"] is None
