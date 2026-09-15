"""GE-110b.5 — the denominator is not the evaluator's to choose, and the UI does not recompute."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.corpus_adequacy import characterise
from eval.evaluators import lexical, lexical_config, load_runs, save_run
from eval.measurement_run import constant, reproduce, run

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


def _run(ev, name, cfg):
    doc = _doc()
    return run(ev, doc, CORPUS, evaluator_name=name, evaluator_config=cfg,
               characterisation=_char(doc))


# ------------------------------------------------------------------ the denominator

def test_the_denominator_is_set_by_the_gold_label_not_the_prediction():
    """Every evaluator faces the same population, whatever it answers."""
    a = _run(constant("Y"), "always-Y", {"a": "Y"})
    b = _run(constant("n/a"), "always-n/a", {"a": "na"})
    c = _run(lexical(), "lexical", lexical_config())
    assert a["n_scored"] == b["n_scored"] == c["n_scored"]


def test_declining_everything_scores_zero_rather_than_escaping_measurement():
    """`always-n/a` used to return 0 of 0 and accuracy None — measured as nothing, not as useless."""
    r = _run(constant("n/a"), "always-n/a", {"a": "na"})
    assert r["n_scored"] > 0
    assert r["element_accuracy"] == 0.0
    assert r["n_declined"] == r["n_scored"]


def test_declining_is_reported_separately_from_being_wrong():
    r = _run(constant("n/a"), "always-n/a", {"a": "na"})
    assert r["n_declined"] > 0
    wrong_not_declined = _run(constant("N"), "always-N", {"a": "N"})
    assert wrong_not_declined["n_declined"] == 0


def test_an_empty_answer_is_no_answer_not_a_wrong_answer():
    r = _run(constant(""), "silent", {"a": ""})
    assert r["n_no_answer"] == r["n_scored"]
    assert r["n_declined"] == 0
    assert r["element_accuracy"] == 0.0


def test_the_constant_identity_still_holds():
    """evaluated population == baseline population == reported denominator."""
    r = _run(constant("Y"), "always-Y", {"a": "Y"})
    assert r["margin_over_strongest_trivial"] == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------ a real evaluator

def test_a_non_constant_evaluator_runs_the_whole_path():
    r = _run(lexical(), "lexical-0.45", lexical_config())
    assert r["element_accuracy"] is not None
    assert len(set(x["predicted"] for x in r["predictions"])) > 1, "should actually branch"
    assert r["limitations"] and r["lineage"]["evaluator_sha"]


def test_a_non_constant_evaluator_reproduces():
    """Constants reproduce trivially; branching reproducing says more about the harness."""
    a = _run(lexical(), "lexical-0.45", lexical_config())
    b = _run(lexical(), "lexical-0.45", lexical_config())
    assert reproduce(a, b)["verdict"] == "reproducible"


def test_changing_the_evaluator_threshold_changes_the_lineage():
    a = _run(lexical(0.45), "lexical", lexical_config(0.45))
    b = _run(lexical(0.60), "lexical", lexical_config(0.60))
    rep = reproduce(a, b)
    assert rep["comparable"] is False and "evaluator_sha" in rep["differing_lineage"]


def test_assessor_config_is_recorded_even_for_a_deterministic_model():
    from eval.evaluators import assessor_config
    cfg = assessor_config("qwen2.5:14b", prompt_version="v3", endpoint="http://localhost:11434")
    assert cfg["model"] == "qwen2.5:14b" and cfg["kind"] == "assessor"


# ------------------------------------------------------------------ persistence

def test_a_run_round_trips(tmp_path):
    r = _run(constant("Y"), "always-Y", {"a": "Y"})
    p = save_run(r, runs_dir=tmp_path)
    back = load_runs(tmp_path)
    assert len(back) == 1
    assert back[0]["lineage"]["labelset_sha"] == r["lineage"]["labelset_sha"]
    assert back[0]["element_accuracy"] == r["element_accuracy"]


def test_the_filename_carries_the_lineage(tmp_path):
    r = _run(constant("Y"), "always-Y", {"a": "Y"})
    p = save_run(r, runs_dir=tmp_path)
    assert r["lineage"]["labelset_sha"][:8] in p.name
    assert r["lineage"]["evaluator_sha"][:8] in p.name


# ------------------------------------------------------------------ the projection

def test_the_measurement_tab_does_not_recompute_anything():
    """A UI that recalculates a metric can disagree with the record it claims to display."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    tab = src.split("with tab_m:")[1]
    for banned in ("measurement_run.run(", "characterise(", "topology(", "baselines(",
                   "sum(", "/ len("):
        assert banned not in tab, f"measurement tab recomputes: {banned}"


def test_the_measurement_tab_reads_the_limitations_from_the_record():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    tab = src.split("with tab_m:")[1]
    assert 'r.get("limitations")' in tab
    assert 'r.get("aggregate_not_computed")' in tab
    assert "baseline_population" in tab
