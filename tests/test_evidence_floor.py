"""
Tests for the evidence floor (WB-017).

The property under test is simple and load-bearing: a control that examined
nothing must not be able to report a pass that looks like a real one. These
tests cover the check side. The runner-side floor that converts a zero-
population PASS into NOT_TESTABLE is tested separately, but it can only work
if every check reports its population honestly — which is what most of this
file asserts.
"""
import pytest

from caa.checks import REGISTRY, CheckResult


# One minimal params dict per registered check, using sources "s" and "t".
PARAMS = {
    "field_present":     {"source": "s", "fields": ["a"]},
    "field_equals":      {"left": {"source": "s", "field": "a"},
                          "right": {"source": "t", "field": "a"},
                          "join": {"left_key": "k", "right_key": "k"}},
    "values_subset":     {"subset": {"source": "s", "field": "a"},
                          "superset": {"source": "t", "field": "a"}},
    "timestamp_before":  {"earlier": {"source": "s", "field": "a"},
                          "later": {"source": "t", "field": "b"},
                          "join": {"left_key": "k", "right_key": "k"}},
    "within_tolerance":  {"source": "s", "order_by": "a",
                          "metrics": {"acc": {"max_drop": 0.1}}},
    "identity_disjoint": {"left": {"source": "s", "field": "a"},
                          "right": {"source": "t", "field": "a"},
                          "join": {"left_key": "k", "right_key": "k"}},
    "date_not_passed":   {"source": "s", "field": "d"},
    "all_pinned":        {"source": "s"},
    "elapsed_within":    {"source": "s", "field": "d", "max_days": 10},
    "threshold_met":     {"source": "s", "field": "v", "order_by": "d", "min": 1},
    "record_count":      {"source": "s", "max": 0},
    "recency_each":      {"source": "s", "field": "d", "max_days": 10},
    "preceded_within":   {"earlier": {"source": "s", "field": "a"},
                          "later": {"source": "t", "field": "b"}, "max_days": 10},
    "rate_within":       {"source": "s", "field": "o", "date_field": "d", "min_records": 10},
}


def test_every_check_has_test_params():
    """A new check without params here would silently skip the sweep below."""
    assert set(PARAMS) == set(REGISTRY), (
        f"params missing for {set(REGISTRY) - set(PARAMS)}, "
        f"stale for {set(PARAMS) - set(REGISTRY)}"
    )


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_empty_source_reports_zero_examined(name):
    """An empty-but-present source is a population of zero, reported as such.

    This is what the runner's floor keys on. A check that returned PASS with a
    non-zero examined count on empty input would slip past the floor.
    """
    result = REGISTRY[name]({"s": [], "t": []}, PARAMS[name])
    assert isinstance(result, CheckResult)
    assert result.examined == 0, f"{name} claimed to examine {result.examined} records of nothing"
    assert result.verdict in ("PASS", "FAIL", "NOT_TESTABLE")


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_missing_source_is_not_testable(name):
    """A source the adapter never provided is a broken feed, not an empty register."""
    result = REGISTRY[name]({}, PARAMS[name])
    assert result.verdict == "NOT_TESTABLE"
    assert "not provided" in result.detail


def test_record_count_distinguishes_zero_of_zero_from_zero_of_n():
    """The defect this whole change exists to fix."""
    p = {"source": "artefact_status",
         "where": {"field": "universal_gap", "equals": True},
         "max": 0}
    check = REGISTRY["record_count"]

    empty = check({"artefact_status": []}, p)
    real = check({"artefact_status": [{"universal_gap": False} for _ in range(12)]}, p)

    assert empty.verdict == real.verdict == "PASS"
    assert empty.examined == 0 and real.examined == 12
    assert empty.detail != real.detail, "two passes over different populations must not read alike"


def test_gov06_cannot_pass_on_an_empty_history():
    """GOV-06 is the tamper control. If policy_history is empty it has tested nothing.

    The check itself returns PASS with examined=0; the runner floor (critical -> 1)
    is what turns that into NOT_TESTABLE. This asserts the raw signal the floor needs.
    """
    p = {"source": "policy_history",
         "where": {"field": "current_unapproved", "equals": True},
         "max": 0}
    result = REGISTRY["record_count"]({"policy_history": []}, p)
    assert result.examined == 0

    populated = REGISTRY["record_count"](
        {"policy_history": [{"version": "1.1.0", "current_unapproved": False}]}, p)
    assert populated.verdict == "PASS" and populated.examined == 1


def test_empty_counterpart_source_now_fails_rather_than_abstains():
    """A deploy with an empty eval_results is a finding, not an untestable state."""
    p = {"earlier": {"source": "eval_results", "field": "run_at"},
         "later": {"source": "deploy_manifest", "field": "deployed_at"},
         "join": {"left_key": "version", "right_key": "version"}}
    result = REGISTRY["timestamp_before"](
        {"eval_results": [], "deploy_manifest": [{"version": "1", "deployed_at": "2026-09-01"}]}, p)
    assert result.verdict == "FAIL"
    assert result.examined == 1
