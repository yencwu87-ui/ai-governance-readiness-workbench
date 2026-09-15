"""GE-110b.2 — measurement topology: four statuses, several baselines, and shortcut risk."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import (CONDITIONAL_NOT_TRIGGERED, DISCRIMINATING,
                                  INSUFFICIENT_VARIATION, UNOBSERVABLE_IN_BUNDLE, baselines,
                                  case_uniformity, characterise, element_status, topology)

ORD = [{"id": e, "observability": "ordinary"} for e in ("e1", "e6", "e7", "e12", "e13")]


def mk(rows):
    return {c: {"label": "?", "verdicts": {e: (v, "") for e, v in d.items()}}
            for c, d in rows.items()}


def test_the_four_statuses_are_distinguished():
    assert element_status(["Y", "N"])[0] == DISCRIMINATING
    assert element_status(["Y", "Y"])[0] == INSUFFICIENT_VARIATION
    assert element_status(["n/a", "n/a"], "conditional")[0] == CONDITIONAL_NOT_TRIGGERED
    assert element_status(["N", "N"], "out_of_band")[0] == UNOBSERVABLE_IN_BUNDLE


def test_out_of_band_wins_over_everything():
    """Even a discriminating pattern does not make an out-of-band element measurable here."""
    assert element_status(["Y", "N"], "out_of_band")[0] == UNOBSERVABLE_IN_BUNDLE


def test_requirements_demand_opportunities_not_outcomes():
    L = mk({"A": {"e1": "Y", "e6": "Y"}, "B": {"e1": "Y", "e6": "Y"}})
    t = topology(characterise(L, elements=ORD[:2]), ORD[:2])
    reqs = {r["element"]: r["requirement"] for r in t["requires"]}
    assert "differing observed labels" in reqs["e1"]
    blob = repr(t["requires"]).lower()
    for forbidden in ("should be", "must be y", "must be n", "target_verdict"):
        assert forbidden not in blob


def test_a_conditional_requirement_names_its_precondition():
    els = [{"id": "e5", "observability": "conditional",
            "precondition": "use_case_impact_relevance"}]
    L = mk({"A": {"e5": "n/a"}, "B": {"e5": "n/a"}})
    t = topology(characterise(L, elements=els), els)
    assert "use_case_impact_relevance" in t["requires"][0]["requirement"]
    assert t["requires"][0]["kind"] == "conditional"


def test_an_out_of_band_element_requires_exclusion_not_a_case():
    els = [{"id": "e14", "observability": "out_of_band"}]
    L = mk({"A": {"e14": "N"}, "B": {"e14": "N"}})
    t = topology(characterise(L, elements=els), els)
    assert t["requires"][0]["kind"] == "capability_finding"
    assert "excluded" in t["requires"][0]["requirement"]


def test_several_trivial_strategies_are_reported_separately():
    L = mk({"A": {"e1": "Y", "e6": "N"}, "B": {"e1": "N", "e6": "n/a"}})
    b = baselines(L, ORD[:2])
    assert set(b["baselines"]) >= {"always_N", "always_Y", "always_not_applicable"}
    assert b["strongest_trivial_score"] == max(b["baselines"].values())


def test_a_corpus_of_internally_uniform_cases_is_shortcut_scorable():
    """Every element discriminates and the corpus still measures document recognition.

    A all-Y against B all-N gives a perfect per-element matrix, and an evaluator that identifies
    which document it is holding and answers uniformly scores full marks without reading any
    evidence. Per-element discrimination cannot see this; only within-case variation can.
    """
    L = mk({"A": {e["id"]: "Y" for e in ORD}, "B": {e["id"]: "N" for e in ORD}})
    t = topology(characterise(L, elements=ORD), ORD)
    u = case_uniformity(L)
    assert t["n_discriminating"] == 5      # looks perfect
    assert u["shortcut_risk"] is True      # and is not


def test_internal_variation_removes_the_shortcut():
    L = mk({"A": {"e1": "Y", "e6": "Y", "e7": "Y", "e12": "Y", "e13": "Y"},
            "B": {"e1": "Y", "e6": "Y", "e7": "N", "e12": "N", "e13": "N"}})
    assert case_uniformity(L)["shortcut_risk"] is False


def test_all_not_applicable_cases_neither_create_nor_dilute_the_risk():
    """They are excluded from the denominator; counting them made the check unfireable."""
    base = {"A": {e["id"]: "Y" for e in ORD}, "B": {e["id"]: "N" for e in ORD}}
    with_na = dict(base, C={e["id"]: "n/a" for e in ORD}, D={e["id"]: "n/a" for e in ORD})
    assert case_uniformity(mk(with_na))["shortcut_risk"] is True
    assert case_uniformity(mk(with_na))["scoring_cases"] == ["A", "B"]


def test_a_single_uniform_case_is_normal():
    """A `none` case is usually uniform. One is fine; all of them is the problem."""
    L = mk({"A": {"e1": "Y", "e6": "N", "e7": "Y"}, "B": {"e1": "N", "e6": "N", "e7": "N"}})
    assert case_uniformity(L)["shortcut_risk"] is False


def test_it_runs_on_the_real_corpus():
    import yaml
    els = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text())["elements"]
    from eval.corpus_adequacy import parse_labels
    L = parse_labels((ROOT / "eval/corpus/M3.6/LABELS.md").read_text())
    t = topology(characterise(L, elements=els), els)
    assert set(t["by_status"]) <= {DISCRIMINATING, INSUFFICIENT_VARIATION,
                                   CONDITIONAL_NOT_TRIGGERED, UNOBSERVABLE_IN_BUNDLE}
    assert t["by_status"].get(UNOBSERVABLE_IN_BUNDLE) == 1   # e14


# ------------------------------------------------------------------ signatures

def test_the_finding_has_a_durable_name():
    from eval.corpus_adequacy import CASE_SIGNATURE_SHORTCUT
    L = mk({"A": {e["id"]: "Y" for e in ORD}, "B": {e["id"]: "N" for e in ORD}})
    assert case_uniformity(L)["finding"] == CASE_SIGNATURE_SHORTCUT == "CASE_SIGNATURE_SHORTCUT"


def test_no_finding_is_recorded_when_there_is_no_risk():
    L = mk({"A": {"e1": "Y", "e6": "N"}, "B": {"e1": "N", "e6": "N"}})
    assert case_uniformity(L)["finding"] is None


def test_the_signature_is_structural_not_the_labels():
    from eval.corpus_adequacy import case_signatures
    L = mk({"A": {"e1": "Y", "e6": "N", "e7": "n/a"}})
    sg = case_signatures(L, [{"id": "e1"}, {"id": "e6"}, {"id": "e7"}])
    assert sg["signatures"]["A"] == "+-·"
    assert sg["legend"]["+"] == "Y"


def test_a_missing_observation_is_distinguishable_from_not_applicable():
    from eval.corpus_adequacy import case_signatures
    L = mk({"A": {"e1": "Y"}})
    sg = case_signatures(L, [{"id": "e1"}, {"id": "e9"}])
    assert sg["signatures"]["A"] == "+?"


def test_two_cases_observing_the_same_thing_collide():
    """A case whose signature matches another adds nothing, whatever its documents say."""
    from eval.corpus_adequacy import case_signatures
    L = mk({"A": {"e1": "Y", "e6": "N"}, "B": {"e1": "Y", "e6": "N"}})
    sg = case_signatures(L, [{"id": "e1"}, {"id": "e6"}])
    assert sg["collisions"] and sg["collisions"][0]["cases"] == ["A", "B"]
    assert sg["distinct_signatures"] == 1


def test_the_real_corpus_has_no_collision_but_is_one_element_from_one():
    import yaml
    from eval.corpus_adequacy import case_signatures, parse_labels
    els = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text())["elements"]
    L = parse_labels((ROOT / "eval/corpus/M3.6/LABELS.md").read_text())
    sg = case_signatures(L, els)
    assert sg["collisions"] == []
    assert sg["distinct_signatures"] == 3
    a, b = sg["signatures"]["M3.6_a.md"], sg["signatures"]["M3.6_b.md"]
    assert sum(x != y for x, y in zip(a, b)) == 1


def test_baselines_stay_descriptive():
    """No threshold, no verdict — the report states them and leaves the judgement to a reader."""
    from eval.corpus_adequacy import baselines
    L = mk({"A": {"e1": "Y", "e6": "N"}, "B": {"e1": "N", "e6": "N"}})
    b = baselines(L, ORD[:2])
    for banned in ("pass", "fail", "threshold", "acceptable", "adequate"):
        assert banned not in repr(b).lower()
