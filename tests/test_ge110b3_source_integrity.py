"""GE-110b.3 — the measurement layer's own source must be accounted for.

A characterisation result is only meaningful if you can say which source produced it. Three
unrecorded mutations of `eval/` happened during this project; the third left
`label_provenance.py` calling a key its own helper no longer returned.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import source_integrity as SI


def test_the_manifest_exists_and_names_an_owner():
    man = SI.load_manifest()
    assert man, "no manifest — run: python -m eval.source_integrity --adopt --owner NAME"
    assert man["adopted_by"].strip()
    assert man["adopted_at"]


def test_no_unrecorded_mutation_of_the_measurement_source():
    """The test that would have caught the GRADE_* surprise the moment it happened."""
    v = SI.verify()
    assert v["ok"], SI.report(v)


def test_every_source_file_is_in_the_manifest():
    man = SI.load_manifest()["files"]
    for rel in SI.SOURCE_FILES:
        if (ROOT / rel).exists():
            assert rel in man, f"{rel} is source and must be pinned"
            assert man[rel]["class"] == "source"


def test_data_drift_is_recorded_but_does_not_fail(tmp_path, monkeypatch):
    """Corpora change as work proceeds; that is not a violation."""
    man = SI.load_manifest()
    data = [k for k, m in man["files"].items() if m["class"] == "data"]
    assert data, "expected corpus files to be recorded as data"
    fake = dict(man)
    fake["files"] = dict(man["files"])
    fake["files"][data[0]] = dict(fake["files"][data[0]], sha256="0" * 64)
    monkeypatch.setattr(SI, "load_manifest", lambda: fake)
    v = SI.verify()
    assert v["ok"] is True
    assert any(d["path"] == data[0] for d in v["drifted"])


def test_source_drift_fails(monkeypatch):
    man = SI.load_manifest()
    fake = dict(man)
    fake["files"] = dict(man["files"])
    fake["files"]["eval/label_provenance.py"] = dict(
        fake["files"]["eval/label_provenance.py"], sha256="0" * 64)
    monkeypatch.setattr(SI, "load_manifest", lambda: fake)
    v = SI.verify()
    assert v["ok"] is False
    assert v["source_drift"][0]["path"] == "eval/label_provenance.py"
    assert "SOURCE DRIFT" in SI.report(v)


def test_adopting_requires_a_named_owner():
    with pytest.raises(ValueError):
        SI.adopt("   ")


def test_the_manifest_records_what_it_superseded(tmp_path, monkeypatch):
    """Re-pinning keeps the prior hash, so a change leaves a trace rather than erasing one."""
    monkeypatch.setattr(SI, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(SI, "SOURCE_FILES", ("eval/source_integrity.py",))
    monkeypatch.setattr(SI, "DATA_GLOBS", ())
    first = SI.adopt("owner-one")
    assert "supersedes" not in first["files"]["eval/source_integrity.py"]
    monkeypatch.setattr(SI, "load_manifest", lambda: {
        "files": {"eval/source_integrity.py": {"sha256": "1" * 64, "bytes": 1, "class": "source"}}})
    second = SI.adopt("owner-two")
    assert second["files"]["eval/source_integrity.py"]["supersedes"] == "1" * 16
    assert second["adopted_by"] == "owner-two"


# ------------------------------------------------------------------ the frozen definition

def test_na_never_by_itself_creates_discrimination():
    """The invariant, pinned. e10 answered N, n/a, N, N varies in applicability and measures nothing."""
    from eval.corpus_adequacy import characterise
    labels = {c: {"label": "partial", "verdicts": {"e10": (v, "")}}
              for c, v in (("d", "N"), ("e", "n/a"), ("f", "N"), ("g", "N"))}
    m = characterise(labels, elements=[{"id": "e10"}])["discrimination_matrix"][0]
    assert m["applicability_variation"] == 2
    assert m["discriminating"] is False


def test_the_two_measures_agree_on_the_real_corpus():
    """They reported 9 against 7 on identical data before this was frozen."""
    import yaml
    from eval.corpus_adequacy import characterise, topology
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    cal = set(doc["calibration_cases"])
    labels = {}
    for j in doc["judgements"]:
        if j.get("provenance") != "adjudicated_case_specific" or j["case"] not in cal:
            continue
        labels.setdefault(j["case"], {"label": "partial", "verdicts": {}})
        labels[j["case"]]["verdicts"][j["element"]] = (j["verdict"], "")
    ch = characterise(labels, elements=doc["elements"])
    n_matrix = sum(1 for m in ch["discrimination_matrix"] if m["discriminating"])
    assert n_matrix == topology(ch, doc["elements"])["by_status"]["DISCRIMINATING"]


def test_headline_diversity_is_reported_without_a_rule():
    import yaml
    from eval.corpus_adequacy import characterise
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    labels = {"d": {"label": "partial", "verdicts": {"e1": ("Y", "")}}}
    ch = characterise(labels, elements=doc["elements"])
    assert ch["headline_outcome_diversity"] == 1
    assert "insufficient" in ch["headline_outcome_status"]
    # Reported, never required — no field instructs an author to manufacture an outcome.
    for banned in ("must contain", "required_outcome", "should produce"):
        assert banned not in repr(ch).lower()
