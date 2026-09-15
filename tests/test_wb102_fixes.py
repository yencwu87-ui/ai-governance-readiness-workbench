"""WB-102 — the four places where "nothing found" and "nothing ran" had collapsed into one.

Each test below pins a distinction the code could not previously express. They are grouped here
rather than spread across the suites they touch because they are one argument: a governance
record must never let a check that did not happen look like a check that happened and passed.
compare.py already held that line for the assessor call. These extend it to the challenger, the
retrieval receipt, the element guards and the triangulation gate.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ------------------------------------------------------------------ decision engine

def _decision(suff="full"):
    return {"action": "accept", "sufficiency": suff, "maturity": 4, "reason": "records tie out"}


def test_blocked_challenge_run_blocks_a_full_rating():
    from governance.decision_engine import evaluate
    out = evaluate(control_id="M3.12", reviewer_decision=_decision(),
                   challenges=[],
                   challenge_run={"validation_status": "blocked",
                                  "validation_error": "quote is not verifiable", "challenges": []})
    assert "CHALLENGE_RUN_BLOCKED" in out["blockers"]
    assert out["decision_eligible"] is False
    assert out["posture"] == "defer"


def test_a_clean_challenge_run_that_found_nothing_does_not_block():
    from governance.decision_engine import evaluate
    out = evaluate(control_id="M3.12", reviewer_decision=_decision(),
                   challenges=[],
                   challenge_run={"validation_status": "ok", "challenges": []})
    assert "CHALLENGE_RUN_BLOCKED" not in out["blockers"]
    assert out["posture"] == "adequate"
    assert out["challenge_summary"]["run_completed"] is True


def test_no_challenge_run_at_all_is_reported_as_unknown_not_as_success():
    from governance.decision_engine import evaluate
    out = evaluate(control_id="M3.12", reviewer_decision=_decision(), challenges=[])
    assert out["challenge_summary"]["run_completed"] is None


# ------------------------------------------------------------------ retrieval receipt

def test_episodic_receipt_can_say_the_ledger_was_unreadable():
    from governance.retrieval_plane import receipt_for
    plane = {"semantic": {}, "episodic": {"matching_episodes": []}, "procedural": {},
             "regulatory": {}}
    clean = receipt_for(plane)
    broken = receipt_for(plane, episodic_error="episodic ledger could not be read: boom")
    assert clean["episodic"]["result_count"] == broken["episodic"]["result_count"] == 0
    # Same count, different fact. Before WB-102 the two receipts were identical.
    assert clean["episodic"]["completed"] is True and clean["episodic"]["degraded"] is False
    assert broken["episodic"]["completed"] is False and broken["episodic"]["degraded"] is True
    assert "episodic" in broken["degraded"]


def test_retrieve_episodes_raises_rather_than_returning_empty_on_an_unreadable_ledger(tmp_path):
    """A ledger that cannot be read at all.

    Note the narrower scope than the name suggests: `events.read_all` already turns a malformed
    *line* into a visible `__unparseable__` record rather than throwing, which is the right call
    and is left alone. What this covers is the case where the ledger cannot be opened — moved,
    permission-denied, or pointing at something that is not a file — which previously returned
    an empty list indistinguishable from a clean run with no matching episode.
    """
    from governance.retrieval_plane import retrieve_episodes, EpisodicUnavailable
    unreadable = tmp_path / "ledger-dir"
    unreadable.mkdir()
    with pytest.raises(EpisodicUnavailable):
        retrieve_episodes("M3.6", "Control Library - MAS", event_path=unreadable)


def test_regulatory_attempt_flags_are_not_constants():
    from governance.retrieval_plane import receipt_for
    plane = {"semantic": {}, "episodic": {}, "procedural": {},
             "regulatory": {"effective_sources": [{}, {}], "web_checks": []}}
    no_web = receipt_for(plane, web_attempted=False)
    with_web = receipt_for(plane, web_attempted=True)
    assert no_web["regulatory"]["web_attempted"] is False
    assert with_web["regulatory"]["web_attempted"] is True
    # The registry half ran either way, and its count must not be read as a web result.
    assert no_web["regulatory"]["registry_count"] == 2
    assert no_web["regulatory"]["web_count"] == 0


# ------------------------------------------------------------------ compare population

class _Ctl:
    id, lib = "M3.12", "Control Library - MAS"


def test_mutual_not_applicable_is_scope_agreement_not_requirement_agreement(monkeypatch):
    import compare as C
    elements = [{"id": f"e{i}", "text": f"element {i}", "scope": "model",
                 "locator": f"x[{i}]"} for i in range(1, 5)]
    monkeypatch.setattr(C, "elements_for", lambda control: elements)
    blind = {"sufficiency": "full", "element_verdicts": [
        {"element_id": "e1", "status": "met"}, {"element_id": "e2", "status": "met"},
        {"element_id": "e3", "status": "not_applicable"}, {"element_id": "e4", "status": "not_applicable"}]}
    ai = {"sufficiency": "full", "elementVerdicts": [
        {"element_id": "e1", "status": "met"}, {"element_id": "e2", "status": "not_evidenced"},
        {"element_id": "e3", "status": "not_applicable"}, {"element_id": "e4", "status": "not_applicable"}]}
    diff = C.compare(blind, ai, _Ctl(), min_compared=2)
    s = diff["summary"]
    # Two genuine comparisons (e1 agree, e2 disagree) — not four with a 75% rate.
    assert s["n_compared"] == 2
    assert s["n_scope_agreed"] == 2
    assert s["agreement_rate"] == 0.5
    assert diff["disagreements"] == ["e2"]


# ------------------------------------------------------------------ element guards

def test_the_original_m36_decomposition_defects_are_all_rejected():
    """The eight items this tool actually emitted on 14 Sep, each for its own reason."""
    from tools.draft_elements import (element_is_obligation, element_subject_match,
                                      element_anchor_match, anchor_is_clean)
    DOC = ("Documentation: Maintain clear records of monitoring activities, results, identified "
           "issues or incidents, and subsequent remediation actions taken for auditability and "
           "ongoing risk management.")
    TRAIN = ("Training and Awareness : Equip persons responsible for monitoring with appropriate "
             "training to support effective monitoring and incident management ; and equip users "
             "of deployed AI with the necessary training and awareness.")
    P25 = "Proposed Guidelines on AI Risk Management | 25 formal independent validation before deployment."

    def kept(element, anchor):
        for ok, _ in (element_is_obligation(element),
                      element_anchor_match(element, anchor)[:2],
                      element_subject_match(element, anchor),
                      anchor_is_clean(anchor)):
            if not ok:
                return False
        return True

    assert not kept("of", DOC)                 # function word
    assert not kept("and", DOC)                # function word
    assert not kept("taken", DOC)              # bare participle
    assert not kept("clear records", DOC)      # noun phrase, no obligation
    # "Perform 25 formal independent validations" — the 25 is a page number.
    assert not kept("Perform 25 formal independent validations", P25)
    # e27/e28 carried an anchor that does not contain them.
    assert not kept("An FI should periodically review aggregate risks", TRAIN)


def test_a_real_obligation_survives_every_guard():
    from tools.draft_elements import (element_is_obligation, element_subject_match,
                                      element_anchor_match, anchor_is_clean)
    anchor = ("The validation process should provide effective challenge to developers and should "
              "cover areas such as: a. conceptual soundness of the design; b. suitability and "
              "quality of data inputs; c. integrity of the implementation.")
    el = ("The validation process should cover conceptual soundness of the design, suitability and "
          "quality of data inputs, and integrity of the implementation.")
    assert element_is_obligation(el)[0]
    assert element_anchor_match(el, anchor)[0]
    assert element_subject_match(el, anchor)[0]
    assert anchor_is_clean(anchor)[0]


def test_subject_guard_no_longer_rejects_a_nested_but_faithful_subject():
    """The inversion WB-102 fixed: this element is correct and was being dropped."""
    from tools.draft_elements import element_subject_match
    anchor = ("An FI should ensure that the AI system is secure, well-governed, and supported by "
              "appropriate controls.")
    ok, reason = element_subject_match("The AI system should be secure", anchor)
    assert ok and reason == ""


def test_subject_guard_flags_rather_than_guesses_when_the_anchor_names_two_actors():
    from tools.draft_elements import element_subject_match
    anchor = ("An FI should ensure that the AI system is secure, well-governed, and supported by "
              "appropriate controls.")
    ok, reason = element_subject_match("The FI should be well-governed", anchor)
    assert ok is True                       # not dropped — a parser would be needed to be sure
    assert reason.startswith("subject_ambiguous")


def test_an_invented_subject_is_still_rejected_outright():
    from tools.draft_elements import element_subject_match
    anchor = ("An FI should ensure that the AI system is secure, well-governed, and supported by "
              "appropriate controls.")
    ok, reason = element_subject_match("The vendor should retain the model", anchor)
    assert ok is False
    assert reason == "obligated_subject_not_supported_by_anchor"


def test_running_headers_are_stripped_before_sentencing():
    from tools.draft_elements import clean_instrument_text
    out = clean_instrument_text(
        "Proposed Guidelines on AI Risk Management | 25 formal independent validation before deployment.")
    assert "25" not in out
    assert out.startswith("formal independent validation")
