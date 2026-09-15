"""Canonical observation compatibility facade.

The authoritative Observation type lives in governance.observation. This module remains as a
backward-compatible import surface for existing plugins and tests.
"""
from dataclasses import dataclass
from governance.observation import (
    Observation, NotAFact, assert_is_fact, declare_observation_envelope,
    declared_observation_envelopes, observe,
)
from governance.observation import evidence_packet as _evidence_packet


@dataclass(frozen=True)
class EvidencePacket:
    packet_id: str
    source_type: str
    provider: str
    target_id: str
    title: str
    locator: str
    excerpt: str
    observed_at: str
    observation_sha256: str
    observation_id: str
    attributes: dict


def observation_to_evidence_packet(observation: Observation, *, title: str | None = None,
                                   excerpt: str | None = None) -> EvidencePacket:
    target = observation.target
    target_id = str(target.get("id") or target or observation.subject)
    locator = str(observation.provenance.get("locator") or observation.provenance.get("endpoint") or observation.source)
    if excerpt is None:
        excerpt = "; ".join(f"{k}={v}" for k, v in sorted(observation.attributes.items()))
    return EvidencePacket(
        packet_id=f"EP-{observation.observation_id}",
        source_type="plugin_observation",
        provider=observation.provider,
        target_id=target_id,
        title=title or f"{observation.resource}: {target_id}",
        locator=locator,
        excerpt=excerpt,
        observed_at=observation.observed_at,
        observation_sha256=observation.content_hash,
        observation_id=observation.observation_id,
        attributes=dict(observation.attributes),
    )


def sha256_json(value):
    import hashlib, json
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = ["Observation", "EvidencePacket", "NotAFact", "assert_is_fact", "observe",
           "declare_observation_envelope", "declared_observation_envelopes",
           "observation_to_evidence_packet", "sha256_json"]
