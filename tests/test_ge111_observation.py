"""GE-111 — Observation is the canonical fact, never the canonical judgement."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import caa.adapters as ad
from governance.observation import (NotAFact, Observation, assert_is_fact, evidence_packet,
                                    from_adapter_result, observe, to_adapter_shape)


def _result(status="ok", records=None, message=""):
    return ad.AdapterResult(status=status, message=message, records=records or [],
                            artefacts=[ad.Artefact("config/model.yaml", "a" * 64, 412)])


# ------------------------------------------------------------------ the fact/judgement line

@pytest.mark.parametrize("key", ["evidence_sufficient", "sufficiency", "compliant", "verdict",
                                 "maturity", "posture", "passed", "decision"])
def test_a_payload_asserting_a_conclusion_is_refused(key):
    with pytest.raises(NotAFact):
        observe("subject", "source", {key: True})


def test_an_ordinary_fact_is_fine():
    o = observe("/repo#models", "caa:model_config", {"model_version": "2026-02-11"})
    assert o.payload["model_version"] == "2026-02-11"


def test_a_judgement_nested_under_a_declared_envelope_is_allowed():
    """The fact is that the assessor said this, which is observable. The rating is payload."""
    o = observe("M3.6", "assessor",
                {"assessor_proposal": {"sufficiency": "partial", "elementVerdicts": []}})
    assert o.payload["assessor_proposal"]["sufficiency"] == "partial"


def test_the_refusal_explains_the_envelope_route():
    with pytest.raises(NotAFact) as exc:
        assert_is_fact({"sufficiency": "full"})
    assert "assessor_proposal" in str(exc.value)


# ------------------------------------------------------------------ identity and freshness

def test_the_content_hash_covers_subject_source_and_payload():
    a = observe("s", "src", {"x": 1})
    b = observe("s", "src", {"x": 1})
    c = observe("s", "src", {"x": 2})
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash


def test_absent_freshness_is_unknown_not_fresh():
    """An observation with no declared freshness is not evidence that it is current."""
    o = observe("s", "src", {"x": 1})
    assert o.freshness_known is False
    assert o.is_stale() is False


def test_a_declared_freshness_expires():
    o = observe("s", "src", {"x": 1}, observed_at="2026-01-01T00:00:00+00:00",
                fresh_for=timedelta(days=7))
    assert o.freshness_known is True
    assert o.is_stale("2026-01-05T00:00:00+00:00") is False
    assert o.is_stale("2026-02-01T00:00:00+00:00") is True


# ------------------------------------------------------------------ CAA migration

def test_each_record_becomes_an_observation_plus_one_for_the_run():
    obs = from_adapter_result(_result(records=[{"a": 1}, {"b": 2}]), adapter="model_config",
                              source_name="models", target="/repo")
    assert len(obs) == 3
    assert sum(1 for o in obs if "adapter_result" in o.payload) == 1


def test_an_adapter_that_errored_is_distinguishable_from_one_that_found_nothing():
    """Both yield zero record-observations. The run observation is where they differ."""
    empty = from_adapter_result(_result(status="ok"), adapter="a", source_name="s", target="/t")
    failed = from_adapter_result(_result(status="error", message="boom"),
                                 adapter="a", source_name="s", target="/t")
    assert len(empty) == len(failed) == 1
    assert empty[0].payload["adapter_result"]["status"] == "ok"
    assert failed[0].payload["adapter_result"]["status"] == "error"
    assert failed[0].payload["adapter_result"]["message"] == "boom"


def test_adapter_status_is_nested_never_top_level():
    obs = from_adapter_result(_result(), adapter="a", source_name="s", target="/t")
    assert "status" not in obs[0].payload
    assert obs[0].payload["adapter_result"]["status"] == "ok"


def test_provenance_carries_the_collector_and_the_artefact_hashes():
    obs = from_adapter_result(_result(records=[{"a": 1}]), adapter="model_config",
                              source_name="models", target="/repo")
    rec = [o for o in obs if "adapter_result" not in o.payload][0]
    assert rec.provenance["adapter"] == "model_config"
    assert rec.provenance["collector"] == "caa.runner"
    assert rec.provenance["artefacts"] == ["a" * 64]


def test_the_existing_consumer_shape_round_trips():
    """The producer migrates; the consumer does not. If the abstraction is wrong, delete the
    projection and nothing downstream noticed it existed."""
    r = _result(records=[{"model_version": "2026-02-11"}, {"deployment_status": "active"}])
    shape = to_adapter_shape(from_adapter_result(r, adapter="model_config",
                                                 source_name="models", target="/repo"))
    assert shape["status"] == r.status
    assert shape["records"] == r.records
    assert shape["adapter"] == "model_config"
    assert len(shape["observation_ids"]) == 3


# ------------------------------------------------------------------ the packet is a projection

def test_the_packet_names_what_it_is_a_projection_of():
    obs = from_adapter_result(_result(records=[{"a": 1}]), adapter="a", source_name="s",
                              target="/t")
    pkt = evidence_packet(obs, title="t")
    assert pkt["is_projection_of"] == [o.observation_id for o in obs]
    assert set(pkt["content_hashes"]) == {o.observation_id for o in obs}


def test_the_packet_says_it_is_not_authoritative():
    pkt = evidence_packet(from_adapter_result(_result(), adapter="a", source_name="s",
                                              target="/t"))
    assert "not authoritative" in pkt["note"].lower()
    assert "evaluate against the observations" in pkt["note"].lower()


def test_the_packet_reports_which_observations_have_unknown_freshness():
    obs = from_adapter_result(_result(records=[{"a": 1}]), adapter="a", source_name="s",
                              target="/t")
    assert evidence_packet(obs)["freshness_unknown"] == [o.observation_id for o in obs]
    fresh = from_adapter_result(_result(records=[{"a": 1}]), adapter="a", source_name="s",
                                target="/t", fresh_for=timedelta(days=1))
    assert evidence_packet(fresh)["freshness_unknown"] == []


def test_the_packet_is_not_a_place_a_judgement_can_hide():
    """Nothing in the projection asserts a conclusion; it renders payloads and provenance."""
    pkt = evidence_packet(from_adapter_result(_result(records=[{"a": 1}]), adapter="a",
                                              source_name="s", target="/t"))
    for banned in ("sufficiency", "compliant", "verdict", "maturity"):
        assert banned not in pkt["text"].lower()


# ------------------------------------------------------------------ slice boundary

def test_lane_a_is_not_migrated_in_this_slice_and_plugins_are_canonicalized():
    """One path proving the abstraction beats five half-converted."""
    src = (ROOT / "governance" / "observation.py").read_text(encoding="utf-8")
    assert "from_adapter_result" in src
    assert "def from_evidence_packet" not in src
    assert "def from_scanner" not in src
    from plugins.github import GitHubPlugin
    assert GitHubPlugin.collect.__globals__["Observation"] is Observation


def test_envelopes_are_registered_by_producers_not_a_central_blocklist():
    from governance.observation import declared_observation_envelopes
    src = (ROOT / "governance" / "observation.py").read_text(encoding="utf-8")
    assert "_PROPOSAL_ENVELOPES" not in src
    declared = set(declared_observation_envelopes())
    assert "adapter_result" in declared
