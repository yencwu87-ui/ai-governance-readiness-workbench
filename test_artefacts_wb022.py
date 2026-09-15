"""WB-022: declared artefacts reach the prompt, and gate a "partial".

Run from repo/ with the venv active:
    pytest test_artefacts_wb022.py -q
"""
from dataclasses import dataclass

from assessor import _artefacts, _prompt, _validate


@dataclass
class C:
    lib: str = "MAS"
    id: str = "M1.1"
    title: str = "Board & senior management accountability for AI risk"
    req: str = "Expectation: Board & senior management accountability for AI risk."
    owner: str = "AI Risk Cttee / Senior Mgmt"
    maps: str = ""
    artefacts: str = "Board mandate; approved framework"


EV = "The Board Risk Committee received an update on AI usage in May 2026."


def test_artefacts_are_split_and_cleaned():
    assert _artefacts(C()) == ["Board mandate", "approved framework"]
    assert _artefacts(C(artefacts="")) == []
    assert _artefacts(C(artefacts="Change records")) == ["Change records"]


def test_artefacts_appear_in_the_prompt():
    p = _prompt(C(), EV, "")
    assert "1. Board mandate" in p and "2. approved framework" in p
    assert "Take each one in turn" in p


def test_prompt_unchanged_when_no_artefacts_declared():
    assert "The evidence must show all of the following" not in _prompt(C(artefacts=""), EV, "")


def _p(**kw):
    base = {"sufficiency": "partial", "proposedMaturity": 3, "excerpt": "",
            "gaps": [], "remediation": [], "reviewerPrompt": ""}
    base.update(kw)
    return base


def test_partial_with_every_artefact_gapped_becomes_none():
    """The M1.1 failure: a real excerpt, but nothing the control asks for is evidenced."""
    out = _validate(_p(excerpt="received an update on AI usage",
                       gaps=["Board mandate", "Approved framework"]),
                    EV, [], ["Board mandate", "approved framework"])
    assert out["sufficiency"] == "none"
    assert out["proposedMaturity"] == 1
    assert any("every item this control requires" in f for f in out["flags"])


def test_partial_with_one_artefact_evidenced_survives():
    """Only fires when ALL artefacts are gapped. One met means partial is right."""
    out = _validate(_p(excerpt="received an update on AI usage", gaps=["Approved framework"]),
                    EV, [], ["Board mandate", "approved framework"])
    assert out["sufficiency"] == "partial"


def test_qualified_gap_does_not_count_as_absence():
    """The over-fire found in the probe. This gap names the artefact but asks for a narrower
    cut of it, against a document that plainly is a validation report. A qualifier is a
    partial finding, not an absent artefact."""
    out = _validate(_p(excerpt="received an update on AI usage",
                       gaps=["Validation & test reports for the specific test cases that were "
                             "re-executed by the reviewer"]),
                    EV, [], ["Validation & test reports"])
    assert out["sufficiency"] == "partial"


def test_short_qualifier_also_survives():
    out = _validate(_p(excerpt="received an update on AI usage",
                       gaps=["Validation & test reports for the <6mth tenure cohort"]),
                    EV, [], ["Validation & test reports"])
    assert out["sufficiency"] == "partial"


def test_artefact_named_with_an_absence_word_still_downgrades():
    out = _validate(_p(excerpt="received an update on AI usage",
                       gaps=["No validation & test reports"]),
                    EV, [], ["Validation & test reports"])
    assert out["sufficiency"] == "none"


def test_phrasing_mismatch_does_not_downgrade():
    """Conservative by design: if the gaps do not match the artefact names, leave the
    rating alone rather than guessing."""
    out = _validate(_p(excerpt="received an update on AI usage",
                       gaps=["no evidence of governance oversight"]),
                    EV, [], ["Board mandate", "approved framework"])
    assert out["sufficiency"] == "partial"


def test_full_is_untouched_by_the_artefact_check():
    out = _validate(_p(sufficiency="full", proposedMaturity=4,
                       excerpt="received an update on AI usage", gaps=[]),
                    EV, [], ["Board mandate", "approved framework"])
    assert out["sufficiency"] == "full"
