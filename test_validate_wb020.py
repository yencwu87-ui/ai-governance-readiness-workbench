"""WB-020: a partial with no surviving verbatim excerpt is not a partial.

Run from repo/ with the venv active:
    pytest test_validate_wb020.py -q
"""
from assessor import _validate


def _proposal(**kw):
    base = {"sufficiency": "partial", "proposedMaturity": 3, "excerpt": "",
            "gaps": ["Risk materiality assessment record"], "remediation": [], "reviewerPrompt": ""}
    base.update(kw)
    return base


EVIDENCE = "Each model change is scored for impact, complexity and reliance."


def test_partial_without_excerpt_downgrades_to_none():
    """The failure this rule exists for: rated partial, nothing evidenced."""
    out = _validate(_proposal(), "Change tickets are approved by the team lead.", [])
    assert out["sufficiency"] == "none"
    assert out["proposedMaturity"] == 1
    assert any("downgraded to none" in f for f in out["flags"])


def test_partial_with_verbatim_excerpt_survives():
    """The rule must not collapse every partial. This is the guard against over-firing."""
    out = _validate(_proposal(excerpt="scored for impact, complexity and reliance",
                              gaps=["Documented criteria"]), EVIDENCE, [])
    assert out["sufficiency"] == "partial"
    assert out["proposedMaturity"] == 3


def test_fabricated_excerpt_falls_through_to_none():
    """Check 2 clears a non-verbatim excerpt; check 4 then sees nothing evidenced."""
    out = _validate(_proposal(excerpt="quarterly fairness testing is performed"), EVIDENCE, [])
    assert out["sufficiency"] == "none"
    assert out["proposedMaturity"] == 1
    assert any("not found verbatim" in f for f in out["flags"])


def test_full_is_untouched():
    out = _validate(_proposal(sufficiency="full", proposedMaturity=4, gaps=[],
                              excerpt="scored for impact, complexity and reliance"), EVIDENCE, [])
    assert out["sufficiency"] == "full"
    assert out["proposedMaturity"] == 4


def test_full_with_gaps_downgrades_to_partial_and_stays_there():
    """Check 3 downgrades full to partial; check 4 must not then push it to none
    when a verbatim excerpt survived."""
    out = _validate(_proposal(sufficiency="full", proposedMaturity=5,
                              excerpt="scored for impact, complexity and reliance",
                              gaps=["Documented criteria"]), EVIDENCE, [])
    assert out["sufficiency"] == "partial"


def test_empty_evidence_is_flagged_not_rated():
    out = _validate(_proposal(sufficiency="none", proposedMaturity=1, gaps=["Anything"]), "   ", [])
    assert any("cannot be established from absence" in f for f in out["flags"])
