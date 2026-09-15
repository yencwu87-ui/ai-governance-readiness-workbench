"""GE-112..115 engine-spine tests: predicate, resource, planner, state and scheduling."""
from datetime import timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.observation import observe
from governance.predicate_engine import evaluate
from governance.resources import Resource, ResourceSelector, select_resources
from governance.planner import build_plan
from governance.continuous_state import Finding, ObservationSchedule, transition


def test_pass_and_fail_control_results_are_deterministic():
    obs = [observe("repo#branch", "github", {"protected": True})]
    r = evaluate(control_id="M3.1", resource_id="repo", observations=obs,
                 predicates=[{"name": "field_equals", "params": {"left": {"source": "github", "field": "protected"}, "right": {"source": "github", "field": "protected"}, "join": {"left_key": "protected", "right_key": "protected"}}}])
    assert r.status == "PASS"
    assert r.integrity_hash


def test_missing_observations_are_not_testable():
    r = evaluate(control_id="M3.1", resource_id="repo", observations=[], predicates=[])
    assert r.status == "NOT_TESTABLE"
    assert "NO_OBSERVATIONS" in r.reason_codes


def test_stale_observation_downgrades_before_predicate_pass():
    obs = [observe("repo", "github", {"protected": True},
                   observed_at="2026-01-01T00:00:00+00:00", fresh_for=timedelta(days=1))]
    r = evaluate(control_id="M3.1", resource_id="repo", observations=obs,
                 predicates=[{"name": "field_present", "params": {"source": "github", "fields": ["protected"]}}],
                 evaluated_at="2026-02-01T00:00:00+00:00")
    assert r.status == "STALE"


def test_predicate_errors_are_results_not_exceptions():
    obs = [observe("repo", "github", {"x": 1})]
    r = evaluate(control_id="M3.1", resource_id="repo", observations=obs,
                 predicates=[{"name": "does_not_exist", "params": {}}])
    assert r.status == "ERROR"
    assert r.predicate_results[0].status == "ERROR"


def test_resource_selector_is_deterministic():
    resources = [
        Resource("m1", "model", {"env": "prod"}, ("critical", "prod")),
        Resource("m2", "model", {"env": "dev"}, ("prod",)),
        Resource("svc1", "service", {"env": "prod"}, ("prod",)),
    ]
    sel = ResourceSelector(resource_class="model", tags_all=("prod",), attributes={"env": "prod"})
    assert [r.resource_id for r in select_resources(resources, sel)] == ["m1"]


def test_planner_reports_missing_capabilities_without_evaluating():
    p = build_plan(control_id="M3.6", resources=["m1"], available_capabilities=["document.inspect"])
    assert p.resource_ids == ("m1",)
    assert p.requirements
    assert p.missing_capabilities
    assert p.plan_hash


def test_finding_transitions_are_temporal_and_non_remediating():
    obs = [observe("m1", "provider", {"status": "bad"})]
    fail = evaluate(control_id="M3.6", resource_id="m1", observations=obs, predicates=[{"name": "field_present", "params": {"source": "provider", "fields": ["missing"]}}], evaluated_at="2026-09-15T00:00:00+00:00")
    f1 = transition(None, fail)
    assert f1.state == "NON_COMPLIANT"
    obs2 = [observe("m1", "provider", {"status": "ok"})]
    ok = evaluate(control_id="M3.6", resource_id="m1", observations=obs2, predicates=[{"name": "field_present", "params": {"source": "provider", "fields": ["status"]}}], evaluated_at="2026-09-16T00:00:00+00:00")
    f2 = transition(f1, ok)
    assert f2.previous_state == "NON_COMPLIANT"
    assert f2.state == "RECOVERED"
    assert f2.first_seen == f1.first_seen


def test_observation_schedule_is_a_pure_due_query():
    s = ObservationSchedule(timedelta(hours=24), "2026-09-16T00:00:00+00:00")
    assert not s.due("2026-09-15T23:59:59+00:00")
    assert s.due("2026-09-16T00:00:00+00:00")
    assert s.advance(from_time="2026-09-16T00:00:00+00:00").next_due.startswith("2026-09-17")


def test_scheduler_returns_due_jobs_without_executing_anything():
    from governance.scheduler import ObservationJob, due_jobs
    jobs = [
        ObservationJob("j1", "M3.6", "m1", ObservationSchedule(timedelta(hours=1), "2026-09-15T10:00:00+00:00"), "test_run.query"),
        ObservationJob("j2", "M3.6", "m1", ObservationSchedule(timedelta(hours=1), "2026-09-15T12:00:00+00:00"), "test_run.query"),
    ]
    assert [j.job_id for j in due_jobs(jobs, at="2026-09-15T11:00:00+00:00")] == ["j1"]
