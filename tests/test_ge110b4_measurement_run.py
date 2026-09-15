"""GE-110b.4 — a measurement result carries its lineage and its limitations."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import characterise
from eval.measurement_run import constant, lineage, limitations, reproduce, run

CORPUS = ROOT / "eval" / "corpus" / "M3.6"


def _doc():
    return yaml.safe_load((CORPUS / "elements.yaml").read_text(encoding="utf-8"))


def _char(doc):
    cal = set(doc["calibration_cases"])
    labels = {}
    for j in doc["judgements"]:
        if j.get("provenance") != "adjudicated_case_specific" or j["case"] not in cal:
            continue
        labels.setdefault(j["case"], {"label": "partial", "verdicts": {}})
        labels[j["case"]]["verdicts"][j["element"]] = (j["verdict"], "")
    return characterise(labels, elements=doc["elements"])


def _run(answer="Y"):
    doc = _doc()
    return run(constant(answer), doc, CORPUS, evaluator_name=f"always-{answer}",
               evaluator_config={"kind": "constant", "answer": answer},
               characterisation=_char(doc))


# ------------------------------------------------------------------ lineage

def test_a_result_carries_four_hashes():
    lin = _run()["lineage"]
    for k in ("contract_sha", "corpus_sha", "labelset_sha", "evaluator_sha"):
        assert lin[k] and len(lin[k]) == 64


def test_lineage_changes_when_the_labels_change():
    doc = _doc()
    a = lineage(doc, CORPUS)
    doc["judgements"][-1] = dict(doc["judgements"][-1], verdict="N")
    b = lineage(doc, CORPUS)
    assert a["labelset_sha"] != b["labelset_sha"]
    assert a["contract_sha"] == b["contract_sha"]


def test_lineage_names_the_case_files_it_ran_against():
    lin = _run()["lineage"]
    assert set(lin["cases"]) == {"d", "e", "f", "g"}
    assert all("sha256" in v for v in lin["case_files"].values())


# ------------------------------------------------------------------ the arithmetic

def test_a_constant_evaluator_exactly_matches_its_own_baseline():
    """The denominator bug: baselines over all labels versus accuracy over Y/N only reported
    always-Y beating the always-Y baseline by 15 points, which cannot happen."""
    r = _run("Y")
    assert r["margin_over_strongest_trivial"] == pytest.approx(0.0, abs=1e-9)
    assert r["baselines"]["always_Y"] == pytest.approx(r["element_accuracy"])
    assert r["baseline_population"] == "scored (Y/N) judgements only"


def test_not_applicable_judgements_are_excluded_not_counted_wrong():
    r = _run("Y")
    assert r["n_scored"] + r["n_excluded_not_applicable"] == r["n_judgements"]
    assert r["n_excluded_not_applicable"] > 0


def test_per_element_accuracy_is_reported():
    r = _run("Y")
    assert r["per_element"]
    assert all(0.0 <= p["accuracy"] <= 1.0 for p in r["per_element"].values())


def test_an_evaluator_that_raises_is_recorded_not_skipped():
    def boom(case, element, evidence, el):
        raise RuntimeError("model unavailable")
    doc = _doc()
    r = run(boom, doc, CORPUS, evaluator_name="broken", characterisation=_char(doc))
    # GE-110b.5: the denominator is the gold population, so a raising evaluator is now scored
    # as answering nothing rather than vanishing from measurement. That is the point of the
    # change — an evaluator cannot shrink its own denominator by failing.
    assert len(r["evaluator_errors"]) == r["n_judgements"]
    assert r["n_scored"] > 0
    assert r["n_no_answer"] == r["n_scored"]
    assert r["element_accuracy"] == 0.0


# ------------------------------------------------------------------ limitations travel

def test_the_aggregate_metric_is_absent_with_a_reason_not_none():
    """None reads as 'computed and came out empty'. Absent-with-a-reason does not."""
    r = _run()
    assert "aggregate_accuracy" not in r
    assert "not defined against it" in r["aggregate_not_computed"]


def test_every_limitation_names_the_claim_it_blocks():
    r = _run()
    codes = {l["code"] for l in r["limitations"]}
    assert {"NO_HEADLINE_VARIATION", "ADJUDICATION_GRADE", "NEAR_IDENTICAL_CASES"} <= codes
    assert all(l["blocks"] and l["detail"] for l in r["limitations"])


def test_the_ai_grade_travels_as_a_limitation_not_as_a_discount():
    """Weighting the score by adjudicator kind would bury the fact in arithmetic."""
    r = _run()
    grade = next(l for l in r["limitations"] if l["code"] == "ADJUDICATION_GRADE")
    assert "ai_adjudicated_candidate" in grade["detail"]
    assert r["element_accuracy"] == pytest.approx(0.707, abs=0.01)  # unweighted


def test_a_corpus_with_headline_variation_drops_that_limitation():
    doc = _doc()
    char = dict(_char(doc), headline_outcome_diversity=3,
                outcome_coverage={"full": 1, "partial": 2, "none": 1})
    lim = {l["code"] for l in limitations(doc, char)}
    assert "NO_HEADLINE_VARIATION" not in lim


def test_no_limitation_is_a_threshold():
    r = _run()
    for banned in ("minimum", "must exceed", "pass mark", "threshold"):
        assert banned not in repr(r["limitations"]).lower()


# ------------------------------------------------------------------ reproducibility

def test_identical_inputs_reproduce():
    assert reproduce(_run("Y"), _run("Y"))["verdict"] == "reproducible"


def test_a_different_evaluator_is_not_comparable_rather_than_a_delta():
    rep = reproduce(_run("Y"), _run("N"))
    assert rep["comparable"] is False
    assert rep["verdict"] == "not_comparable"
    assert "evaluator_sha" in rep["differing_lineage"]


def test_same_lineage_different_predictions_is_a_finding_about_the_evaluator():
    a = _run("Y")
    b = dict(a, predictions=[dict(r, predicted="N") if i == 0 else r
                             for i, r in enumerate(a["predictions"])])
    rep = reproduce(a, b)
    assert rep["comparable"] is True
    assert rep["reproducible"] is False
    assert rep["verdict"] == "non_deterministic_evaluator"
    assert rep["n_differences"] == 1
