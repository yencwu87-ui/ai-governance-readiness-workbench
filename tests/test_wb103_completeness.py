"""WB-103/104 — the completeness pass, and element identity across a contract revision."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import completeness as CP
from governance.element_identity import (diff_contracts, duplicate_obligations, identify,
                                         similarity, slug, uid)


def _app():
    """Import the UI module, skipping if Streamlit is absent.

    GE-110: only the display tests in this file need `app`; the completeness and identity tests
    are engine-layer. Importing `app` at module scope made a headless run stop here with
    ModuleNotFoundError, which took every engine test after it with it. Skipping one test is
    honest; coupling the engine suite to the UI is not.
    """
    pytest.importorskip("streamlit", reason="UI-layer test")
    import app
    return app


class _Ctl:
    id = "M3.12"
    lib = "Control Library - MAS"
    artefacts = "Change records; Approval evidence; Post-implementation review; as applicable"


def _doc(path, text):
    return {"path": path, "text": text}


# ------------------------------------------------------------------ completeness

def test_a_named_file_is_a_stronger_hit_than_a_passing_mention():
    docs = [_doc("/e/change_records_Q1.csv", "CHG-1 approved"),
            _doc("/e/policy.md", "This policy explains what approval evidence should contain.")]
    out = CP.scan(_Ctl(), docs)
    by = {r["artefact"]: r for r in out["artefacts"]}
    assert by["Change records"]["status"] == "present"
    # A policy describing approval evidence is not approval evidence.
    assert by["Approval evidence"]["status"] == "ambiguous"
    assert by["Post-implementation review"]["status"] == "absent"


def test_a_category_label_is_reported_unmatchable_not_absent():
    out = CP.scan(_Ctl(), [_doc("/e/change_records.csv", "x")])
    by = {r["artefact"]: r for r in out["artefacts"]}
    assert by["as applicable"]["status"] == "unmatchable"
    assert "as applicable" not in out["gaps"]


def test_an_empty_bundle_is_not_testable_rather_than_all_gaps():
    """The failure that contaminated the Lane A record: assessing against nothing."""
    out = CP.scan(_Ctl(), [])
    assert out["testable"] is False
    assert out["gaps"] == []
    # Every *matchable* artefact is NOT_TESTABLE. Whether a declared artefact is a category
    # label is a fact about the workbook row, not about the bundle, so that verdict stands
    # either way.
    assert {r["status"] for r in out["artefacts"]} == {"NOT_TESTABLE", "unmatchable"}
    assert all(r["status"] == "NOT_TESTABLE" for r in out["artefacts"]
               if r["artefact"] != "as applicable")
    assert "below the floor" in out["not_testable_reason"]
    assert "NOT_TESTABLE" in CP.headline(out)


def test_the_pass_never_emits_a_rating_or_an_element_verdict():
    """This is what makes it safe to show before the blind read."""
    out = CP.scan(_Ctl(), [_doc("/e/change_records.csv", "CHG-1")])
    banned = {"sufficiency", "maturity", "proposedMaturity", "elementVerdicts",
              "element_verdicts", "rating"}
    assert banned.isdisjoint(out)
    assert banned.isdisjoint(set().union(*(set(r) for r in out["artefacts"])))


def test_completeness_says_nothing_about_whether_the_requirement_is_met():
    out = CP.scan(_Ctl(), [_doc("/e/change_records.csv", "a"), _doc("/e/approval_evidence.md", "b"),
                           _doc("/e/post_implementation_review.md", "c")])
    assert out["complete"] is True
    assert "says nothing yet about whether the requirement is met" in CP.headline(out)


def test_the_bundle_hash_moves_when_a_document_is_added_or_edited():
    a = [_doc("/e/one.md", "x")]
    b = [_doc("/e/one.md", "x"), _doc("/e/two.md", "y")]
    c = [_doc("/e/one.md", "x EDITED")]
    assert CP.hash_chunks(a) != CP.hash_chunks(b)
    assert CP.hash_chunks(a) != CP.hash_chunks(c)
    assert CP.hash_chunks(a) == CP.hash_chunks(list(a))


def test_substring_over_firing_is_not_reintroduced():
    """WB-022's first matcher read a sentence denying an artefact as evidence of it."""
    docs = [_doc("/e/gap_memo.md",
                 "No post-implementation review was completed for this release.")]
    out = CP.match_artefact("Change records", {d["path"]: d["text"] for d in docs})
    assert out["status"] == "absent"


# ------------------------------------------------------------------ element identity

def test_the_same_obligation_has_the_same_uid_regardless_of_position():
    text = "Re-validation triggers are defined and are proportionate to assessed risk materiality."
    assert uid(text) == uid("  Re-validation   triggers are DEFINED and are proportionate to "
                            "assessed risk materiality.  ")
    assert uid(text) != uid(text + " Approved by the board.")


def test_the_slug_is_readable_and_deterministic():
    s = slug("For AI assessed as high risk materiality, formal independent validation is "
             "performed before deployment by competent and objective personnel.")
    assert s == slug("For AI assessed as high risk materiality, formal independent validation "
                     "is performed before deployment by competent and objective personnel.")
    assert "validation" in s and " " not in s


def test_two_ids_carrying_one_obligation_are_detected():
    """`validate_elements` rejects a duplicate id; it cannot see a duplicate requirement."""
    els = [{"id": "e1", "text": "Change records link approval to the deployed version."},
           {"id": "e9", "text": "change records link approval to the deployed version"}]
    dupes = duplicate_obligations(els)
    assert len(dupes) == 1
    assert sorted(dupes[0]["ids"]) == ["e1", "e9"]


def test_an_identical_obligation_carries_its_labels_across_a_renumber():
    old = [{"id": "e3", "text": "Validation was performed by someone who did not build the model",
            "a": "Y", "b": "N", "c": "N"}]
    new = [{"id": "e11", "text": "Validation was performed by someone who did not build the model"}]
    d = diff_contracts(old, new)
    assert d["summary"]["carried"] == 1
    assert d["carried"][0]["old_id"] == "e3" and d["carried"][0]["new_id"] == "e11"
    assert d["carried"][0]["labels"] == {"a": "Y", "b": "N", "c": "N"}


def test_a_reworded_obligation_is_proposed_never_applied():
    old = [{"id": "e5", "text": "A validation outcome is recorded and dated", "a": "Y"}]
    new = [{"id": "e5", "text": "A validation outcome is recorded and dated by a named owner"}]
    d = diff_contracts(old, new)
    assert d["summary"]["carried"] == 0
    assert d["summary"]["proposed_for_human"] == 1
    assert d["proposed"][0]["decision"] == "pending_human"
    # The old label is shown for context, but no label is attached to the new element.
    assert "labels" not in d["proposed"][0]


def test_a_retired_obligation_is_named_so_its_labels_are_not_silently_lost():
    old = [{"id": "e2", "text": "Testing covers behaviour under stress conditions", "a": "Y"}]
    new = [{"id": "e1", "text": "The board approves the AI risk appetite annually"}]
    d = diff_contracts(old, new)
    assert d["summary"]["retired"] == 1
    assert d["retired"][0]["old_id"] == "e2"
    assert d["retired"][0]["labels"] == {"a": "Y"}


def test_the_real_m36_revision_carries_nothing_and_says_so():
    """The 10 -> 14 rewrite, run against both real contracts.

    `elements.yaml` asserts that the prior labels could not be copied. This turns that assertion
    into a measurement: no obligation survived, and the closest pair scores about 0.31, well
    under the near-match threshold. Abandoning the labels was right; now it is demonstrated.
    """
    import yaml
    old_p = ROOT / "requirements/contracts/M3.6_elements_v1_10el.yaml"
    new_p = ROOT / "eval/corpus/M3.6/elements.yaml"
    if not old_p.exists():
        pytest.skip("prior M3.6 contract not present")
    old = yaml.safe_load(old_p.read_text(encoding="utf-8"))["elements"]
    new = yaml.safe_load(new_p.read_text(encoding="utf-8"))["elements"]
    d = diff_contracts(old, new)
    assert d["summary"]["carried"] == 0
    assert d["summary"]["proposed_for_human"] == 0
    assert d["summary"]["retired"] == len(old)
    assert max(r["closest"] for r in d["new"]) < 0.5


def test_similarity_is_symmetric_and_bounded():
    a, b = "independent validation before deployment", "validation performed before deployment"
    assert similarity(a, b) == similarity(b, a)
    assert 0.0 <= similarity(a, b) <= 1.0
    assert similarity(a, a) == 1.0


def test_identify_leaves_existing_fields_alone():
    rows = identify([{"id": "e1", "text": "A record is kept", "a": "Y", "decided_by": "x"}])
    assert rows[0]["a"] == "Y" and rows[0]["decided_by"] == "x"
    assert rows[0]["uid"].startswith("el-")


# ------------------------------------------------------------------ the UI path

def test_the_evidence_splitter_is_the_one_the_challenger_quotes_against():
    """Completeness and challenge must see the same documents, or a gap is unfalsifiable."""
    from governance.challenge_pointers import parse_evidence_sources
    ev = {"text": "--- Source: change_records_Q1.csv ---\nCHG-1 approved.\n\n"
                  "--- Source: pir.md ---\nPIR done."}
    docs = CP.chunks_from_evidence(ev)
    assert {d["path"] for d in docs} == set(parse_evidence_sources(ev["text"]))


def test_manual_evidence_is_one_document_not_many():
    ev = {"text": "Para one.\n\nPara two.\n\nPara three."}
    docs = CP.chunks_from_evidence(ev)
    assert len(docs) == 1 and docs[0]["path"] == "reviewer_supplied"


def test_the_bundle_guard_is_callable_outside_assess():
    """app.py writes `proposed` directly and never calls cycle.assess().

    A guard reachable only from `assess()` would not exist for the UI — the same class of
    mistake as enforcing blindness by screen order. This pins that it is public.
    """
    import core.cycle as cyc
    assert hasattr(cyc, "check_bundle_unchanged")
    assert "check_bundle_unchanged" in cyc.__all__
    # An unknown cycle is a no-op, not a crash: the guard must never be the thing that breaks
    # a review.
    cyc.check_bundle_unchanged("no-such-cycle")


def test_the_review_row_exposes_completeness_without_making_gaps_block():
    import review_queue

    class _C:
        key, id, title, lib = "k", "M3.12", "Change management", "Control Library - MAS"

    state = {"evidence": {"text": "x"}, "stage": "open",
             "completeness": {"testable": True, "gaps": ["Approval evidence"]}}
    row = review_queue.project_control(_C(), state=state)
    assert row["has_completeness"] is True
    assert row["completeness_gaps"] == 1
    # The scan having run is the completion. Proceeding with a known gap is a recordable choice.
    assert row["has_evidence"] is True


# ------------------------------------------------------------------ WB-106 step display

def _row(**kw):
    base = {"has_evidence": True, "has_completeness": False, "has_read": False,
            "has_proposal": False, "proposal_error": False, "has_compare": False,
            "decision": False, "challenge": {"unresolved": 0, "unresolved_strong": 0}}
    base.update(kw)
    return base


def test_no_hand_maintained_step_list_survives_in_the_ui():
    """The drift that produced two disagreeing indicators: 7 steps in one, 5 in the other."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '("Evidence", "done"),' not in src, "an inline step strip is back"
    assert src.count("REVIEW_STEPS = [") == 1


def test_step_projection_covers_every_step_in_order():
    from app import REVIEW_STEPS, _review_step_states, _review_label
    states = _review_step_states(_row(), "reading")
    assert [lbl for lbl, _ in states] == [_review_label(s) for s in REVIEW_STEPS]
    assert len(states) == 7


def test_a_ready_proposal_is_held_not_ticked_while_the_reading_is_open():
    """The blindness order must not be contradicted by the progress bar.

    A green tick on AI assessment while Your reading is still pending showed a completed step
    ahead of the step that gates it. It never revealed the rating, but it announced that a
    proposal was ready and had succeeded.
    """
    _review_step_states = _app()._review_step_states
    states = dict(_review_step_states(_row(has_proposal=True), "reading"))
    assert states["AI assessment"] == "held"
    assert states["Your reading"] == "now"


def test_once_the_reading_is_recorded_the_proposal_shows_as_done():
    _review_step_states = _app()._review_step_states
    states = dict(_review_step_states(_row(has_proposal=True, has_read=True), "assessment"))
    assert states["AI assessment"] == "done"
    assert states["Your reading"] == "done"


def test_completeness_is_done_when_the_scan_ran_even_with_open_gaps():
    _review_step_states = _app()._review_step_states
    states = dict(_review_step_states(_row(has_completeness=True), "reading"))
    assert states["Completeness"] == "done"


# ------------------------------------------------------------------ WB-107

def test_the_report_line_no_longer_crashes_on_a_workspace_decision():
    """KeyError 'aiSufficiency' fired on every decision recorded through the review workspace.

    `cycle.decide()` never writes that key — only `pipeline.record_decision` does, and the app
    stopped using it. The guard read `.get()` and the body read `[...]`, so the guard was always
    true and the body always raised.
    """
    _ai_proposed_clause = _app()._ai_proposed_clause
    d = {"sufficiency": "partial", "maturity": 2, "reviewer": "wu yenching",
         "at": "2026-09-14T08:19:00"}
    assert _ai_proposed_clause(d, {}) == " (no assessor proposal was recorded)"


def test_a_missing_proposal_is_not_reported_as_a_difference_of_opinion():
    _ai_proposed_clause = _app()._ai_proposed_clause
    d = {"sufficiency": "partial"}
    assert "AI proposed" not in _ai_proposed_clause(d, {})
    assert "AI proposed" not in _ai_proposed_clause(d, {"model": "error"})
    assert "assessor call failed" in _ai_proposed_clause(d, {"model": "error"})


def test_a_real_disagreement_is_still_reported():
    _ai_proposed_clause = _app()._ai_proposed_clause
    assert _ai_proposed_clause({"sufficiency": "partial"}, {"sufficiency": "none"}) == " (AI proposed none)"
    assert _ai_proposed_clause({"sufficiency": "partial"}, {"sufficiency": "partial"}) == ""


def test_a_blocked_challenge_is_not_a_completed_challenge_step():
    """The green ✓ on Challenge for a pass where no challenge was admitted."""
    _review_step_states = _app()._review_step_states
    blocked = _row(has_read=True, has_proposal=True, has_compare=True,
                   challenge={"unresolved": 0, "unresolved_strong": 0,
                              "ran": True, "blocked": True, "produced_a_result": False})
    assert dict(_review_step_states(blocked, "decision"))["Challenge"] == "blocked"


def test_a_challenge_that_never_ran_is_not_complete_either():
    _review_step_states = _app()._review_step_states
    never = _row(has_read=True, has_proposal=True, has_compare=True,
                 challenge={"unresolved": 0, "unresolved_strong": 0,
                            "ran": False, "blocked": False, "produced_a_result": False})
    assert dict(_review_step_states(never, "challenge"))["Challenge"] != "done"


def test_a_clean_challenge_with_nothing_unresolved_is_complete():
    _review_step_states = _app()._review_step_states
    clean = _row(has_read=True, has_proposal=True, has_compare=True,
                 challenge={"unresolved": 0, "unresolved_strong": 0,
                            "ran": True, "blocked": False, "produced_a_result": True})
    assert dict(_review_step_states(clean, "decision"))["Challenge"] == "done"


def test_the_dossier_distinguishes_blocked_from_nothing_found():
    import challenge_dossier
    common = dict(control_id="M3.6", control_title="t", reviewer="wu yenching",
                  blind={"sufficiency": "partial"}, challenges=[],
                  challenger_model="qwen2.5:14b", knowledge=[])
    silent = challenge_dossier.create_dossier(**common)
    blocked = challenge_dossier.create_dossier(**common, validation_status="blocked")
    assert silent["status"] == "no_challenges"
    assert silent["reading_was_challenged"] is True
    assert blocked["status"] == "blocked"
    assert blocked["challenge_outcome"] == "blocked"
    # The record must not let an unchallengeable run read as an unchallenged one.
    assert blocked["reading_was_challenged"] is False


# ------------------------------------------------------------------ WB-108 queue row

def test_the_queue_does_not_tick_the_assessor_ahead_of_the_blind_read():
    """`AI ✓ · Read —` across every row is a pre-read signal at queue scale."""
    _queue_markers = _app()._queue_markers
    line = _queue_markers(_row(has_proposal=True, has_read=False))
    assert "AI ⏸" in line
    assert "AI ✓" not in line


def test_the_queue_ticks_the_assessor_once_the_read_exists():
    _queue_markers = _app()._queue_markers
    assert "AI ✓" in _queue_markers(_row(has_proposal=True, has_read=True))


def test_a_failed_assessor_call_is_distinct_from_one_that_never_ran():
    _queue_markers = _app()._queue_markers
    assert "AI !" in _queue_markers(_row(has_proposal=True, proposal_error=True))
    assert "AI —" in _queue_markers(_row(has_proposal=False))


def test_the_queue_shows_every_step_the_workspace_does():
    """The queue previously showed four of the seven steps, omitting Completeness and Challenge.

    Decision is the one step not repeated, because the row already carries it as `Next:`.
    """
    _a = _app(); _queue_markers, REVIEW_STEPS, QUEUE_LABELS = _a._queue_markers, _a.REVIEW_STEPS, _a.QUEUE_LABELS
    assert set(QUEUE_LABELS) == set(REVIEW_STEPS) - {"decision"}
    line = _queue_markers(_row())
    for step in REVIEW_STEPS:
        if step == "decision":
            continue
        assert QUEUE_LABELS[step] in line, step


def test_a_blocked_challenge_shows_as_blocked_in_the_queue_too():
    _queue_markers = _app()._queue_markers
    line = _queue_markers(_row(has_read=True, has_proposal=True, has_compare=True,
                               challenge={"unresolved": 0, "unresolved_strong": 0,
                                          "ran": True, "blocked": True,
                                          "produced_a_result": False}))
    assert "Challenge ⚠" in line
