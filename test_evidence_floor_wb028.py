"""WB-028: the evidence floor tests in_scope, not examined.

`examined` is the source population before the scope filter. A control whose filter empties
the population was clearing the floor on records it never evaluated. Observed in one bundle
on 2026-09-10:

    MCM-09  PASS          0 of 15 records in scope, all within 7 days
    OVS-02  NOT_TESTABLE  examined 0 records, floor is 1 - 0 of 0 records matched

Both evaluated nothing. Only the one whose source was empty was caught.

Run from repo/:
    pytest test_evidence_floor_wb028.py -q
"""
import pytest

from caa import checks
from caa.runner import run_controls

POLICY = {"evidence_floor": {"by_severity": {"critical": 1, "high": 1, "medium": 1, "low": 0}}}


def _control(cid="TEST-01", severity="high"):
    return {"id": cid, "severity": severity, "frequency": "on_commit", "domain": "test",
            "title": "t", "assertion": "a", "inputs": [], "check": "stub", "params": {},
            "human_gate": None}


def _inventory():
    return {"sources": {"src": {"status": "ok", "records": [], "artefacts": []}}}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Remove the stub after each test. checks.REGISTRY is global, and
    tests/test_evidence_floor.py::test_every_check_has_test_params asserts that every
    registered check has test params - a stub left behind fails it, and only when the
    files run together."""
    yield
    checks.REGISTRY.pop("stub", None)


def _with_stub(result):
    checks.REGISTRY["stub"] = lambda ctx, p: result
    return run_controls([_control()], _inventory(), "on_commit", POLICY)[0]


def test_filter_emptied_population_is_floored():
    """The MCM-09 case: a healthy source, a filter that excludes everything."""
    r = _with_stub(checks.CheckResult("PASS", "0 of 15 in scope, all within 7 days",
                                      examined=15, in_scope=0))
    assert r["machine_verdict"] == "NOT_TESTABLE"
    assert "only 0 were in scope" in r["detail"]
    assert r["examined"] == 15 and r["in_scope"] == 0


def test_empty_source_is_floored_and_reads_differently():
    """The OVS-02 case. Same outcome, different message, so a reader can tell them apart."""
    r = _with_stub(checks.CheckResult("PASS", "0 of 0 records matched", examined=0, in_scope=0))
    assert r["machine_verdict"] == "NOT_TESTABLE"
    assert "only 0 were in scope" not in r["detail"]
    assert "examined 0 records" in r["detail"]


def test_real_population_still_passes():
    r = _with_stub(checks.CheckResult("PASS", "0 of 40 records matched", examined=40, in_scope=40))
    assert r["machine_verdict"] == "PASS"


def test_one_in_scope_record_clears_a_floor_of_one():
    """Strictly stronger, never weaker: where in_scope equals examined the behaviour is
    unchanged from the pre-WB-028 floor."""
    r = _with_stub(checks.CheckResult("PASS", "0 of 1 records matched", examined=1, in_scope=1))
    assert r["machine_verdict"] == "PASS"


def test_floor_does_not_touch_fail():
    """The floor only ever downgrades a PASS. A FAIL on a tiny population is still a FAIL —
    finding a breach in one record is a finding, not a sampling problem."""
    r = _with_stub(checks.CheckResult("FAIL", "1 of 15 in scope breached", examined=15, in_scope=0))
    assert r["machine_verdict"] == "FAIL"
