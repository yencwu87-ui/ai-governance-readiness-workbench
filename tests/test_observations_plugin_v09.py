import json
from pathlib import Path

import events
from observations import Observation, observation_to_evidence_packet


def test_observation_packet_is_structured_and_hashable():
    obs = Observation.create(
        observation_id="github-test-1",
        provider="github",
        target={"type": "github_repo", "id": "org/repo", "branch": "main"},
        resource="branch_protection",
        observed_at="2026-09-13T12:00:00+00:00",
        attributes={"required_approving_review_count": 2, "required_pull_request_reviews": True},
        provenance={"method": "github_api", "locator": "github_api:GET /repos/org/repo/branches/main/protection"},
    )
    packet = observation_to_evidence_packet(obs)
    assert packet.source_type == "plugin_observation"
    assert packet.observation_sha256 == obs.integrity["sha256"]
    assert "required_approving_review_count=2" in packet.excerpt


def test_observed_event_is_global_and_hash_chain_remains_intact(tmp_path):
    path = tmp_path / "events.jsonl"
    observation = {"observation_id": "o-1", "provider": "github", "resource": "branch_protection"}
    events.append("observed", cycle_id="", actor="tester", control_id="branch_protection",
                  framework="github", payload={"observation": observation}, path=path)
    rows = events.observations(path)
    assert len(rows) == 1
    assert rows[0]["cycle_id"] == ""
    assert rows[0]["payload"]["observation"]["observation_id"] == "o-1"
    assert events.verify(path)["intact"] is True
