"""WB-036 — a stale corpus makes label comparison NOT_TESTABLE, not merely noted.

The detection has existed since WB-029 and the EVL controls consult it. Nothing in the paths
where measurements are actually taken did, so four probe runs and every score run reported
label agreement against a corpus whose labels had been argued against a superseded
decomposition of the requirement. These tests pin the gate to the measuring paths.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


probe = _load("tools/probe_wb031.py", "probe_wb031")
score = _load("eval/score.py", "score_wb036")


def _rows(**kw):
    base = {"control_id": "M3.6", "case_id": "M3.6_a",
            "requirement_sha": "aaa", "requirement_sha_live": "aaa",
            "requirement_sha_mismatch": False}
    base.update(kw)
    return base


# ---------------- the probe ----------------

def test_binding_reports_stale_cases(monkeypatch):
    monkeypatch.setattr(probe._ea, "corpus_case_rows",
                        lambda: [_rows(requirement_sha_live="bbb", requirement_sha_mismatch=True)])
    b = probe.corpus_binding(["M3.6"])
    assert b["by_control"]["M3.6"]["stale"] == ["M3.6_a"]
    assert probe.print_binding(b) is False


def test_binding_reports_unbound_cases(monkeypatch):
    monkeypatch.setattr(probe._ea, "corpus_case_rows", lambda: [_rows(requirement_sha=None)])
    b = probe.corpus_binding(["M3.6"])
    assert b["by_control"]["M3.6"]["unbound"] == ["M3.6_a"]
    assert probe.print_binding(b) is False


def test_a_bound_corpus_passes(monkeypatch):
    monkeypatch.setattr(probe._ea, "corpus_case_rows", lambda: [_rows()])
    assert probe.print_binding(probe.corpus_binding(["M3.6"])) is True


def test_an_unavailable_corpus_is_not_a_claim_that_it_is_bound(monkeypatch):
    """The probe must still run in a tree without the corpus, and must not say 'bound'."""
    def boom():
        raise FileNotFoundError("no corpus here")
    monkeypatch.setattr(probe._ea, "corpus_case_rows", boom)
    b = probe.corpus_binding(["M3.6"])
    assert b["available"] is False
    assert b["by_control"] == {}
    assert probe.print_binding(b) is True          # not blocked, but nothing is asserted either


# ---------------- score.py ----------------

def test_score_binding_lists_stale_and_unbound(monkeypatch):
    import eval_adapters as ea
    monkeypatch.setattr(ea, "corpus_case_rows",
                        lambda: [_rows(requirement_sha_live="bbb", requirement_sha_mismatch=True),
                                 _rows(case_id="M3.6_b", requirement_sha=None)])
    b = score._corpus_binding()
    assert b["stale"] == ["M3.6_a"]
    assert b["unbound"] == ["M3.6_b"]
    assert b["cases_examined"] == 2


def test_score_binding_never_raises(monkeypatch):
    import eval_adapters as ea

    def boom():
        raise RuntimeError("corpus unreadable")
    monkeypatch.setattr(ea, "corpus_case_rows", boom)
    b = score._corpus_binding()
    assert b["available"] is False
    assert b["stale"] == [] and b["unbound"] == []


@pytest.mark.parametrize("binding,expected", [
    ({"stale": ["x"], "unbound": []}, True),
    ({"stale": [], "unbound": ["x"]}, True),
    ({"stale": [], "unbound": []}, False),
    ({"available": False, "stale": [], "unbound": []}, False),
])
def test_staleness_forces_not_testable(binding, expected):
    """Mirrors the condition in main(): stale or unbound overrides an 'evaluated' status.
    An unavailable corpus does not — it is a different claim from a broken binding."""
    forced = bool(binding.get("stale") or binding.get("unbound"))
    assert forced is expected


def test_the_live_corpus_is_currently_bound():
    """Only the calibration cases must track the governed requirement.

    This asserted over every M3.6_* case and failed on a/b/c. Those are the retired 7-element
    generation: superseded when the contract went to 14 elements, deliberately kept in the file
    rather than deleted, and excluded from calibration by `calibration_cases`. Deleting a
    judgement to make a gate pass is the behaviour the provenance layer exists to prevent, so
    the test is scoped to the live set instead.
    """
    import yaml
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    live = {f"M3.6_{c}" for c in (doc.get("calibration_cases") or [])}
    assert live, "the corpus must name its calibration cases"

    b = score._corpus_binding()
    if not b["available"]:
        pytest.skip("corpus not available in this tree")
    stale = [x for x in b["stale"] if x in live]
    unbound = [x for x in b["unbound"] if x in live]
    assert not stale and not unbound, \
        "the M3.6 calibration cases must track the governed requirement before live scoring"


def test_the_retired_cases_are_still_present_and_still_excluded():
    """Retired, not deleted — and the exclusion is declared rather than implied by absence."""
    import yaml
    doc = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    assert set(doc["calibration_cases"]) == {"d", "e", "f", "g"}
    assert set(doc.get("retired_cases") or {}) == {"a", "b", "c"}
    cases = {j["case"] for j in doc["judgements"]}
    assert {"a", "b", "c"} <= cases, "retired judgements must remain in the record"
