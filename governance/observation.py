"""GE-111 — Observation: the canonical fact.

The distinction this module exists to hold, stated once:

    an Observation records what was observed.
    it never records what that observation means.

"the model version is 2026-02-11" is an observation. "the evidence is sufficient" is not — it is
an evaluation, and it belongs downstream. The one case where sufficiency legitimately appears in
a payload is when it was *itself observed from a governed source*: an assessor produced a
proposal, and the fact that it did so, with that content, at that time, under that model, is a
fact about the assessor. The proposal's rating is payload data, not the Observation's verdict.
`assert_is_fact` enforces the boundary.

This matters because the project has repeatedly found the same failure in different costumes — a
model's opinion laundered into a record that reads like a measurement, a test procedure returned
as a finding, a validator's output treated as authority. Making the fact/judgement line
structural rather than conventional is the only version that survives contact.

    Observation                 what was seen, with provenance and freshness
        ↓
    EvidencePacket              a governed projection for human reading
        ↓
    (later) Predicate           evaluation over observations
        ↓
    ControlResult

`EvidencePacket` is a projection, deliberately. It is what a reviewer reads, assembled from
observations and carrying their provenance forward; it is not the source of truth and nothing
downstream should evaluate against it. That inversion — rendering becoming canonical — is what
the earlier Lane A / Lane B split had produced.

Scope note: this is the CAA vertical slice only. Lane A evidence and the plugin surface are
deliberately not migrated here. One path proving the abstraction is worth more than five paths
half-converted.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SCHEMA = "ge111.observation.1"

#: Payload keys that assert a governance conclusion rather than record a fact. An Observation
#: carrying one of these at the top level has stopped being an observation.
_JUDGEMENT_KEYS = {
    "evidence_sufficient", "sufficient", "sufficiency", "compliant", "is_compliant",
    "control_result", "pass", "passed", "fail", "failed", "verdict", "adequate",
    "maturity", "proposed_maturity", "posture", "decision",
}

#: Where a judgement-shaped payload IS the fact: the observation is that this source emitted
#: this output, not that the output is true. The payload is then nested under the source's own
#: key so nothing reads it as the Observation's own verdict.
_ENVELOPE_REGISTRY: set[str] = set()

def declare_observation_envelope(kind: str) -> str:
    """Producer-owned declaration of a payload envelope that may contain judgement-shaped output."""
    k = str(kind).strip()
    if not k:
        raise ValueError("observation envelope kind is required")
    _ENVELOPE_REGISTRY.add(k)
    return k

def declared_observation_envelopes() -> tuple[str, ...]:
    return tuple(sorted(_ENVELOPE_REGISTRY))



def _sha(obj: Any) -> str:
    b = (obj.encode("utf-8") if isinstance(obj, str)
         else obj if isinstance(obj, bytes)
         else json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return hashlib.sha256(b).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotAFact(ValueError):
    """Raised when a payload asserts a conclusion instead of recording an observation."""


def assert_is_fact(payload: dict[str, Any]) -> None:
    """Refuse a payload that states a governance conclusion at the top level.

    Nested under a declared envelope it is allowed, because the fact being recorded is then
    "this source said this", which is observable. At the top level it is the Observation itself
    claiming the conclusion, which is the inversion this module exists to prevent.
    """
    if not isinstance(payload, dict):
        raise NotAFact("payload must be a mapping")
    bad = sorted(k for k in payload if str(k).lower() in _JUDGEMENT_KEYS)
    if bad:
        raise NotAFact(
            f"payload asserts a conclusion at the top level: {', '.join(bad)}. An Observation "
            f"records what was observed, not what it means. If the fact is that a source emitted "
            f"this, nest it under a producer-declared observation envelope (for example `assessor_proposal`) so the record says who "
            f"claimed it.")


@dataclass
class Observation:
    """One observed fact, with enough provenance to be re-checked and enough freshness metadata
    to be found stale later."""
    observation_id: str
    subject: str                      # what was observed — resource, control, file, system
    source: str                       # who or what observed it
    observed_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    fresh_until: str | None = None
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        assert_is_fact(self.payload)
        if not self.content_hash:
            self.content_hash = _sha({"subject": self.subject, "source": self.source,
                                      "payload": self.payload})

    def is_stale(self, at: str | None = None) -> bool:
        """Freshness is a property of the observation, not of whoever reads it.

        `fresh_until` absent means unknown rather than fresh — an observation with no declared
        freshness is not evidence that it is current. GE-112 will act on this; recording it now
        means the field exists before anything depends on it.
        """
        if not self.fresh_until:
            return False
        now = at or _now()
        return str(now) > str(self.fresh_until)

    @property
    def freshness_known(self) -> bool:
        return self.fresh_until is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


    @classmethod
    def create(cls, *, observation_id: str, provider: str, target: dict[str, Any],
               resource: str, observed_at: str, attributes: dict[str, Any],
               provenance: dict[str, Any]) -> "Observation":
        """Compatibility constructor for legacy plugin callers.

        The returned object is the GE-111 canonical Observation; provider/target/resource/
        attributes are compatibility views over the canonical source/subject/payload fields.
        """
        return cls(
            observation_id=observation_id,
            subject=f"{resource}:{target.get('id') or target}",
            source=provider,
            observed_at=observed_at,
            payload=dict(attributes),
            provenance={**dict(provenance), "target": dict(target), "resource": resource},
        )

    @property
    def provider(self) -> str:
        return self.source

    @property
    def target(self) -> dict[str, Any]:
        return dict(self.provenance.get("target") or {})

    @property
    def resource(self) -> str:
        return str(self.provenance.get("resource") or self.subject.split(":", 1)[0])

    @property
    def attributes(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def integrity(self) -> dict[str, str]:
        return {"sha256": self.content_hash}


def make_id(subject: str, source: str, observed_at: str, payload: dict) -> str:
    return "obs-" + _sha({"s": subject, "src": source, "at": observed_at, "p": payload})[:16]


def observe(subject: str, source: str, payload: dict[str, Any], *,
            observed_at: str | None = None, provenance: dict | None = None,
            fresh_for: timedelta | None = None) -> Observation:
    at = observed_at or _now()
    fresh_until = None
    if fresh_for is not None:
        fresh_until = (datetime.fromisoformat(at) + fresh_for).isoformat(timespec="seconds")
    return Observation(observation_id=make_id(subject, source, at, payload),
                       subject=subject, source=source, observed_at=at,
                       payload=payload, provenance=provenance or {},
                       fresh_until=fresh_until)



# ---------------------------------------------------------------- CAA migration

declare_observation_envelope("adapter_result")

def from_adapter_result(result: Any, *, adapter: str, source_name: str, target: str,
                        observed_at: str | None = None,
                        fresh_for: timedelta | None = None) -> list[Observation]:
    """`AdapterResult` -> Observations. The first and only migration in this slice.

    One Observation per record, plus one for the adapter run itself. The run-level observation
    matters: an adapter that returned nothing and an adapter that errored both produce zero
    record-observations, and the distinction has to survive somewhere. It is the same rule the
    challenge envelope and the retrieval receipt already follow — a check that did not happen
    must never look like a check that found nothing.

    The adapter's `status` is carried as `adapter_result`, nested, because "the adapter reported
    ok" is a fact about the adapter and not a conclusion about the control.
    """
    at = observed_at or _now()
    status = str(getattr(result, "status", "") or "")
    message = str(getattr(result, "message", "") or "")
    records = list(getattr(result, "records", []) or [])
    artefacts = [asdict(a) if hasattr(a, "__dataclass_fields__") else dict(a)
                 for a in (getattr(result, "artefacts", []) or [])]

    prov = {"adapter": adapter, "source_name": source_name, "target": target,
            "collector": "caa.runner"}
    out = [observe(subject=f"{target}#{source_name}", source=f"caa:{adapter}",
                   payload={"adapter_result": {"status": status, "message": message,
                                               "record_count": len(records),
                                               "artefacts": artefacts}},
                   observed_at=at, provenance=prov, fresh_for=fresh_for)]
    for i, rec in enumerate(records):
        out.append(observe(subject=f"{target}#{source_name}[{i}]", source=f"caa:{adapter}",
                           payload=dict(rec) if isinstance(rec, dict) else {"value": rec},
                           observed_at=at,
                           provenance=dict(prov, record_index=i,
                                           artefacts=[a.get("sha256") for a in artefacts]),
                           fresh_for=fresh_for))
    return out


def to_adapter_shape(observations: Iterable[Observation]) -> dict[str, Any]:
    """Project Observations back into the shape `caa.runner.discover` already emits.

    The existing consumer is unchanged by this slice. Migrating the producer without migrating
    the consumer in the same step is what keeps the slice vertical and reversible — if the
    abstraction turns out wrong, the projection is deleted and nothing downstream noticed it
    existed.
    """
    obs = list(observations)
    run = next((o for o in obs if "adapter_result" in o.payload), None)
    env = (run.payload["adapter_result"] if run else {})
    return {
        "adapter": (run.provenance.get("adapter") if run else ""),
        "status": env.get("status", ""),
        "message": env.get("message", ""),
        "records": [o.payload for o in obs if "adapter_result" not in o.payload],
        "artefacts": env.get("artefacts", []),
        "observation_ids": [o.observation_id for o in obs],
    }


# ---------------------------------------------------------------- projection

def evidence_packet(observations: Iterable[Observation], *, title: str = "") -> dict[str, Any]:
    """A governed, human-readable projection of observations. Not the source of truth.

    Carries every observation id and content hash forward, so a reviewer reading the packet can
    always get back to the facts it was rendered from. Nothing downstream should evaluate against
    this — it exists for a person to read.
    """
    obs = list(observations)
    lines = []
    for o in obs:
        head = f"--- Source: {o.source} · {o.subject} ---"
        body = json.dumps(o.payload, indent=2, ensure_ascii=False, default=str)
        lines.append(f"{head}\n{body}")
    return {
        "schema": "ge111.evidence-packet.1",
        "title": title,
        "is_projection_of": [o.observation_id for o in obs],
        "content_hashes": {o.observation_id: o.content_hash for o in obs},
        "sources": sorted({o.source for o in obs}),
        "observed_between": ([min(o.observed_at for o in obs), max(o.observed_at for o in obs)]
                             if obs else None),
        "freshness_unknown": [o.observation_id for o in obs if not o.freshness_known],
        "text": "\n\n".join(lines),
        "note": ("Projection of the observations listed above. Not authoritative — evaluate "
                 "against the observations, not against this rendering."),
    }
