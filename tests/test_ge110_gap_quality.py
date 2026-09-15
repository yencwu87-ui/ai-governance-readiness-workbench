"""GE-110 — a gap must be a finding about the evidence.

From a live D1.3 panel: six "gaps" listed as e1..e6, and five "suggested actions" that were the
same sentences again. Tracing them to `control_contracts.yaml`, e2..e6 were the control's Test of
Operating Effectiveness steps — "Sample boundary events in the period", "Inspect the most recent
recertification" — relabelled as requirement elements. D1.3 declares exactly one element.

The contract already forbade this. Its own `test_provenance` reads: "ToD/ToE, evidence floors,
challenge banks and internet knowledge do not create requirement obligations." `elementVerdicts`
enforced it (WB-031 drops a verdict naming an undeclared element); `gaps` did not, and gaps are
what the UI renders.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assessor

CONTRACT = {
    "test_of_operating_effectiveness": [
        {"id": "O1", "text": "Obtain the enforced configuration as at a date and compare it, "
                             "field by field, to the approved boundary."},
        {"id": "O3", "text": "Sample boundary events in the period: blocks, referrals and "
                             "overrides. Trace each override to an approver with authority and "
                             "a recorded reason."},
    ],
    "test_of_design": [
        {"id": "D5", "text": "Confirm periodic recertification of granted authority, with a "
                             "defined cadence and an accountable reviewer."},
    ],
}
ELEMENTS = [{"id": "e1", "text": "The organization must ensure that cap the agent's blast "
                                 "radius before build."}]


EVIDENCE = ("The boundary was approved on 3 March. evidence body. "
            "The recertification log covers Q1.")


def _run(gaps, remediation=None, elements=ELEMENTS, contract=CONTRACT, excerpt=""):
    """`excerpt` defaults to empty, which trips the unrelated WB-020 rule (a `partial` with no
    surviving verbatim excerpt is downgraded). Tests that assert on maturity pass a real one so
    they are measuring this guard and not that one."""
    out = {"sufficiency": "partial", "proposedMaturity": 3, "excerpt": excerpt, "rationale": "r",
           "gaps": list(gaps), "remediation": list(remediation or []), "flags": [],
           "elementVerdicts": []}
    return assessor._validate(out, EVIDENCE, [], [], elements=elements, contract=contract)


def _flagged(res, needle):
    return any(needle in f for f in res["flags"])


def test_a_toe_step_returned_as_a_gap_is_flagged_as_a_procedure():
    res = _run(["Sample boundary events in the period: blocks, referrals and overrides. Trace "
                "each override to an approver with authority and a recorded reason."])
    assert _flagged(res, "restate a test step")
    assert res.get("procedural_gaps")


def test_a_tod_step_counts_too():
    res = _run(["Confirm periodic recertification of granted authority, with a defined cadence "
                "and an accountable reviewer."])
    assert _flagged(res, "restate a test step")


def test_a_gap_repeating_the_element_text_is_flagged_as_a_restatement():
    res = _run(["The organization must ensure that cap the agent's blast radius before build."])
    assert _flagged(res, "repeat the requirement text")


def test_a_proposal_made_entirely_of_restatements_is_capped_at_maturity_one():
    """The whole panel was this: one broken element plus five audit procedures."""
    res = _run([ELEMENTS[0]["text"],
                CONTRACT["test_of_operating_effectiveness"][0]["text"],
                CONTRACT["test_of_operating_effectiveness"][1]["text"]])
    assert _flagged(res, "describes the control, it does not assess the evidence")
    assert res["proposedMaturity"] == 1
    assert res.get("gaps_are_restatements") is True


def test_a_real_finding_is_left_alone():
    res = _run(["No approver name appears on the November boundary change.",
                "The recertification log covers Q1 only; Q2 and Q3 are absent."],
               excerpt="The boundary was approved on 3 March.")
    assert not _flagged(res, "restate a test step")
    assert not _flagged(res, "repeat the requirement text")
    assert not res.get("gaps_are_restatements")
    assert res["proposedMaturity"] > 1


def test_remediation_that_repeats_a_gap_verbatim_is_removed():
    """Two columns showing one column's worth of information."""
    gap = "No approver name appears on the November boundary change."
    res = _run([gap], remediation=[gap, "Obtain the change ticket and identify the approver."])
    assert _flagged(res, "repeated a gap verbatim")
    assert res["remediation"] == ["Obtain the change ticket and identify the approver."]


def test_a_leading_verb_does_not_disguise_a_repeat():
    """The panel's e2 was O1 with 'Obtain' stripped; the reverse dodge is prepending one."""
    res = _run(["The enforced configuration as at a date and compare it, field by field, to the "
                "approved boundary."])
    assert _flagged(res, "restate a test step")


def test_short_gaps_are_never_matched():
    """Matching is length-guarded so a terse real finding cannot collide with a long procedure."""
    res = _run(["No approver."])
    assert not _flagged(res, "restate a test step")


def test_the_guards_are_inert_without_a_contract():
    res = _run(["Sample boundary events in the period: blocks, referrals and overrides."],
               contract={})
    assert not _flagged(res, "restate a test step")
