"""Shared element execution envelope.

The same element key connects governed contract, retrieval, testing/provider capability hints,
evidence observations, assessment and challenge. This is an orchestration/data contract, not a
new source of requirements.
"""
from __future__ import annotations
from typing import Any

from governance.element_registry import get, testing_metadata


def make_envelope(control_id: str, element_id: str, framework: str = "", requirement_id: str = "R1") -> dict[str, Any]:
    e = get(control_id, element_id, framework, requirement_id)
    if not e:
        raise KeyError(f"ungoverned element: {control_id}.{requirement_id}.{element_id}")
    return {
        "control_id": control_id,
        "requirement_id": requirement_id,
        "element_id": element_id,
        "element_key": e["element_key"],
        "requirement_text": e["text"],
        "locator": e["locator"],
        "testing": testing_metadata(control_id, framework, element_id),
        "retrieval": {"local": [], "testing": [], "internet": []},
        "observations": [],
        "tests": [],
        "assessment": {},
        "challenge": {},
    }


def attach_observation(envelope: dict[str, Any], observation: dict[str, Any], *, capability: str = "") -> dict[str, Any]:
    """Attach a plugin observation only to the already-governed element."""
    row = dict(observation)
    row["element_id"] = envelope["element_id"]
    row["element_key"] = envelope["element_key"]
    if capability:
        row["capability"] = capability
    envelope.setdefault("observations", []).append(row)
    return envelope


def attach_test(envelope: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    row = dict(result)
    row["element_id"] = envelope["element_id"]
    row["element_key"] = envelope["element_key"]
    envelope.setdefault("tests", []).append(row)
    return envelope
