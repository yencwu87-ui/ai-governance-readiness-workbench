"""GE-110b.1 invariant — inherited provenance is not calibration data."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import characterise, discrimination_target, parse_labels
from eval.label_provenance import (ADJUDICATED, INHERITED, NotCalibrationData, admissibility,
                                   assert_calibration_data, calibration_admissible, summary)

GOOD = {"case": "a", "element": "e1", "verdict": "Y",
        "justification": "§5 names Independent Model Validation as the reviewer",
        "provenance": ADJUDICATED, "source_refs": ["M3.6_a.md#§5"],
        "labelled_by": "wu yenching", "adjudicator_kind": "human",
        "labelled_at": "2026-09-14"}


def test_an_adjudicated_judgement_is_admissible():
    ok, why = admissibility(GOOD)
    assert ok and why == ""


def test_inherited_provenance_is_never_admissible():
    """The invariant, stated once: migration data must not become calibration data."""
    ok, why = admissibility(dict(GOOD, provenance=INHERITED))
    assert not ok and "inherited" in why


def test_per_case_alone_is_not_enough():
    """A sentence in the right cell is not an adjudication."""
    ok, _ = admissibility(dict(GOOD, provenance="per_case"))
    assert not ok


@pytest.mark.parametrize("missing,field", [
    ("justification", ""), ("source_refs", []), ("labelled_at", "")])
def test_each_required_field_is_required(missing, field):
    ok, _ = admissibility(dict(GOOD, **{missing: field}))
    assert not ok


@pytest.mark.parametrize("who", ["claude-unconfirmed", "unrecorded", "",
                                 "pending-human-relabel-2026-09-14"])
def test_a_string_that_identifies_nobody_is_rejected(who):
    """`claude-unconfirmed` has been in this corpus from the start."""
    ok, why = admissibility(dict(GOOD, labelled_by=who))
    assert not ok and "nobody" in why


def test_personhood_is_declared_not_inferred_from_the_name():
    """The hole this replaced: the check asked whether the string "names a person".

    `GPT-5.6 Luna` passed it, because a model name looks exactly like a person's name. No
    blocklist fixes that — it is one new model name away from being wrong again. The record
    states the fact instead.
    """
    ok, why = admissibility({k: v for k, v in GOOD.items() if k != "adjudicator_kind"})
    assert not ok and "adjudicator_kind" in why
    ok, _ = admissibility(dict(GOOD, adjudicator_kind="ai", labelled_by="GPT-5.6 Luna"))
    assert ok


def test_an_ai_adjudicated_corpus_is_admissible_but_not_human_grade():
    from eval.label_provenance import GRADE_AI, GRADE_HUMAN, calibration_admissible
    ai = {"judgements": [dict(GOOD, adjudicator_kind="ai", labelled_by="GPT-5.6 Luna")]}
    hu = {"judgements": [GOOD]}
    assert calibration_admissible(ai)["ready"] is True
    assert calibration_admissible(ai)["grade"] == GRADE_AI
    assert calibration_admissible(ai)["human_adjudicated"] is False
    assert calibration_admissible(hu)["grade"] == GRADE_HUMAN


def test_the_gate_raises_rather_than_returning_a_status():
    doc = {"judgements": [dict(GOOD, provenance=INHERITED)]}
    with pytest.raises(NotCalibrationData) as exc:
        assert_calibration_data(doc)
    assert exc.value.report["inadmissible"] == 1


def test_a_fully_adjudicated_corpus_passes_the_gate():
    doc = {"judgements": [GOOD, dict(GOOD, case="b", verdict="N",
                                     justification="§5 is absent from _b",
                                     source_refs=["M3.6_b.md"])]}
    assert assert_calibration_data(doc)["ready"] is True


def test_structural_completeness_and_calibration_readiness_are_separate_facts():
    doc = {"judgements": [dict(GOOD, provenance=INHERITED)]}
    s = summary(doc)
    assert s["n_judgements"] == 1          # structurally migrated
    assert s["calibration_ready"] is False  # and not calibration data


def test_the_calibration_set_is_scoped_and_superseded_rows_are_kept():
    """M3.6 now holds both generations: 42 inherited (a/b/c) and 52 adjudicated (d/e/f/g).

    The gate reads `calibration_cases`. Superseded rows stay in the file, because deleting a
    judgement to pass a gate is the behaviour this layer exists to prevent.
    """
    p = ROOT / "eval" / "corpus" / "M3.6" / "elements.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert set(doc["calibration_cases"]) == {"d", "e", "f", "g"}
    assert len(doc["judgements"]) == 94
    adm = calibration_admissible(doc)
    assert adm["admissible"] == 52 and adm["ready"] is True
    assert adm["grade"] == "ai_adjudicated_candidate"
    assert not any(j["element"] == "e14" for j in doc["judgements"]
                   if j.get("provenance") == ADJUDICATED), "e14 must not carry a verdict"
    assert doc["capability_findings"][0]["element"] == "e14"


def test_m312_is_still_migrated_but_not_calibration_data():
    for ctl in ("M3.12",):
        p = ROOT / "eval" / "corpus" / ctl / "elements.yaml"
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        s = summary(doc)
        assert s["n_judgements"] > 0
        assert s["adjudicated"] == 0
        assert s["calibration_ready"] is False
        assert calibration_admissible(doc)["admissible"] == 0


# ------------------------------------------------------------------ coverage target

MD = """
### `x_a.md` → **partial**

| element | | where |
|---|---|---|
| `e1` | N | n |
| `e2` | Y | n |

---

### `x_b.md` → **none**

| element | | where |
|---|---|---|
| `e1` | N | n |
| `e2` | N | n |
"""


def test_the_target_names_coverage_gaps_not_verdicts():
    t = discrimination_target(characterise(parse_labels(MD)))
    assert "e1" in t["needs_a_discriminating_observation"]
    assert "e2" not in t["needs_a_discriminating_observation"]  # already Y/N
    assert "full" in t["missing_outcomes"]
    # No field anywhere says what a new case should be rated.
    blob = repr(t).lower()
    for forbidden in ("should be full", "target_verdict", "expected_label"):
        assert forbidden not in blob


def test_an_element_never_observed_as_met_is_named():
    t = discrimination_target(characterise(parse_labels(MD)))
    assert "e1" in t["never_observed_as_met"]
