"""One canonical requirement text, and three separate verification facts."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import semantic_canon as sc
from governance import verification_semantics as vs


# ------------------------------------------------------------------ canonical text

def test_every_derived_view_agrees_with_the_canon():
    """The D1.2 drift class: same element, three files, two repaired, one missed."""
    c = sc.check()
    assert c["clean"], sc.report(c)


def test_all_seven_derived_views_are_actually_walked():
    c = sc.check()
    assert len(c["views"]) == 7
    assert sum(v["elements"] for v in c["views"]) > 1000


def test_sync_only_runs_one_direction():
    """A derived file must not be able to promote its own wording to canonical."""
    src = (ROOT / "governance" / "semantic_canon.py").read_text(encoding="utf-8")
    assert "def sync" in src
    for reverse in ("def reverse_sync", "def promote", "canonical_from_derived"):
        assert f"{reverse}(" not in src


def test_drift_is_detected_not_tolerated(tmp_path):
    canon = tmp_path / "governance/knowledge/control_contracts.yaml"
    canon.parent.mkdir(parents=True)
    canon.write_text(yaml.safe_dump({"controls": [
        {"control_id": "X", "elements": [{"id": "e1", "text": "Records are kept."}]}]}))
    view = tmp_path / "governance/knowledge/contracts/mas.yaml"
    view.parent.mkdir(parents=True)
    view.write_text(yaml.safe_dump({"controls": [
        {"control_id": "X", "elements": [{"id": "e1", "text": "Records are retained."}]}]}))
    c = sc.check(tmp_path)
    assert c["drift"] == 1 and not c["clean"]
    sc.sync(tmp_path)
    assert sc.check(tmp_path)["clean"]


# ------------------------------------------------------------------ verification semantics

def test_predicate_presence_alone_does_not_make_an_element_deterministic():
    """`verification_reason` was literally "Executable predicate specification exists."."""
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["reviewer_identity"]}})
    assert r["predicate_available"] is True
    assert r["verification"] == vs.HUMAN_JUDGEMENT
    assert "no declared provider supplies" in r["verification_reason"]


def test_a_declared_provider_that_supplies_the_observations_makes_it_deterministic():
    caps = [{"provider": "IdentityPlugin", "observes": ["reviewer_identity", "developer_identity"]}]
    r = vs.resolve({"predicate_spec": {"present": True,
                                       "requires": ["reviewer_identity", "developer_identity"]}},
                   capabilities=caps)
    assert r["verification"] == vs.DETERMINISTIC


def test_partial_capability_is_not_enough():
    caps = [{"provider": "IdentityPlugin", "observes": ["reviewer_identity"]}]
    r = vs.resolve({"predicate_spec": {"present": True,
                                       "requires": ["reviewer_identity", "developer_identity"]}},
                   capabilities=caps)
    assert r["verification"] == vs.HUMAN_JUDGEMENT


def test_out_of_band_survives_a_capability():
    caps = [{"provider": "P", "observes": ["x"]}]
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["x"]},
                    "verification": vs.OUT_OF_BAND}, capabilities=caps,
                   observability="out_of_band")
    assert r["verification"] == vs.OUT_OF_BAND


def test_a_registry_corpus_conflict_is_recorded_not_resolved():
    caps = [{"provider": "P", "observes": ["x"]}]
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["x"]}},
                   capabilities=caps, observability="ordinary")
    assert r["verification"] == vs.DETERMINISTIC
    assert r["corpus_observability"] == "ordinary"
    assert "Both are retained" in r["verification_conflict"]


def test_the_live_registry_claims_no_deterministic_elements():
    """With no providers declared, nothing is deterministically evaluable — the honest answer.

    Nineteen elements previously claimed DETERMINISTIC on the strength of a predicate existing,
    including M3.6 e6 ("reviewed by parties not involved in its development"), which the
    adjudicated corpus treats as human judgement.
    """
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    modes = [e.get("verification") for c in doc["controls"] for e in c["elements"]]
    assert modes.count(vs.DETERMINISTIC) == 0
    assert modes.count(vs.OUT_OF_BAND) == 1


def test_m36_elements_carry_their_corpus_observability():
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    m36 = next(c for c in doc["controls"] if c["control_id"] == "M3.6")
    obs = [e.get("corpus_observability") for e in m36["elements"]]
    assert obs.count("ordinary") == 7
    assert obs.count("conditional") == 6
    assert obs.count("out_of_band") == 1


def test_predicate_availability_is_still_recorded():
    """Downgrading the mode must not lose the fact that the predicate exists."""
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    m36 = next(c for c in doc["controls"] if c["control_id"] == "M3.6")
    assert sum(1 for e in m36["elements"] if e.get("predicate_available")) == 14
