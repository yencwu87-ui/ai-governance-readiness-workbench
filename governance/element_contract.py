"""Validation and executable metadata for requirement elements.

An element is an atomic governance obligation, not a sentence fragment. Test dimensions and
implementation hints may enrich an element, but cannot create additional obligations silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_ALLOWED = {"design", "operation"}


@dataclass(frozen=True)
class ElementContract:
    id: str
    text: str
    kind: str = "design"
    verification: str = "evidence"
    evidence_types: tuple[str, ...] = ()
    capability_hints: tuple[str, ...] = ()
    failure_condition: str = ""


def validate_element(e: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    eid = str(e.get("id") or "").strip()
    text = " ".join(str(e.get("text") or "").split())
    kind = str(e.get("kind") or "design").strip().lower()
    if not eid:
        errors.append("missing element id")
    if len(text.split()) < 5:
        errors.append(f"{eid}: element is too short to be a testable obligation")
    if kind not in _ALLOWED:
        errors.append(f"{eid}: invalid kind {kind!r}")
    # failure_condition belongs to optional executable verification metadata, not the governed
    # requirement element itself. Do not force testing metadata into authoritative obligations.
    return errors


def validate_elements(elements: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for e in elements:
        eid = str(e.get("id") or "")
        if eid in seen:
            errors.append(f"duplicate element id: {eid}")
        seen.add(eid)
        errors.extend(validate_element(e))
    if not elements:
        errors.append("element contract is empty")
    return errors


def element_testing_context(control_id: str, framework: str = "") -> dict[str, dict[str, Any]]:
    """Return advisory verification metadata; it never changes the governed requirement."""
    if str(control_id) != "M3.6" or str(framework) not in {"MAS", "Control Library - MAS"}:
        return {}
    import yaml
    from pathlib import Path
    p = Path(__file__).resolve().parent / "knowledge" / "element_testing.yaml"
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("elements") or {}
    except Exception:
        return {}
